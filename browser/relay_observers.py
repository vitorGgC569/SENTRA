"""Concrete server-only Edge relay observers, sharing the existing CP.

No browser is launched, navigated, adopted by URL, or substituted by Electron.
An operator binds an existing Edge CDP browser endpoint and target to the exact
OS process/profile and enrolled extension worker. Each proof independently
reads reviewed collector bytes in that physical target. Frames/caches are not
authentication. No Run/Grant is created. Optional websockets is never installed
here. Disabled CDP, missing package or unknown UI schema is unavailable.
"""
from __future__ import annotations

from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import time
from urllib.parse import urlsplit

from sentra_core.conversations import _encode, _decode
from .protected_assets import checkpoint


class RelayObserverUnavailable(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value, name, pattern=r"[A-Za-z0-9_.:-]{1,256}"):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("invalid reviewed " + name)
    return value


def _account(snapshot):
    values = [snapshot.get("account_id"), snapshot.get("user_id")]
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value) for value in values):
        raise RelayObserverUnavailable("committed account identity schema is unknown")
    return _digest(values)


def _endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or not parsed.port
            or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]{8,160}", parsed.path)
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("reviewed loopback Edge browser websocket endpoint required")
    return parsed


def _listener_pid(port):
    """Read Windows listener ownership; a websocket claiming Edge is insufficient."""
    if os.name != "nt":
        raise RelayObserverUnavailable("Windows Edge process identity is unavailable")
    from ctypes import wintypes
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                    wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    api.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    if api(None, ctypes.byref(size), False, 2, 3, 0) not in (0, 122) or not 4 <= size.value <= 4_000_000:
        raise RelayObserverUnavailable("Edge listener ownership cannot be read")
    data = ctypes.create_string_buffer(size.value)
    if api(data, ctypes.byref(size), False, 2, 3, 0) != 0:
        raise RelayObserverUnavailable("Edge listener ownership cannot be read")
    raw = data.raw[:size.value]; count = struct.unpack_from("<I", raw)[0]
    if 4 + count * 24 > len(raw):
        raise RelayObserverUnavailable("invalid Windows listener table")
    matches = []
    for index in range(count):
        state, address, local_port, _, _, pid = struct.unpack_from("<6I", raw, 4 + index * 24)
        if state == 2 and socket.ntohs(local_port & 65535) == port:
            # Wildcard exposure is not the reviewed loopback-only observer.
            if struct.pack("<I", address) != socket.inet_aton("127.0.0.1"):
                raise RelayObserverUnavailable("Edge CDP listener is not loopback-only")
            matches.append(pid)
    if len(matches) != 1:
        raise RelayObserverUnavailable("Edge CDP listener has no unique OS owner")
    return matches[0]


def _process(pid, expected_executable, expected_sha):
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.QueryFullProcessImageNameW.restype = wintypes.BOOL
    api.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                                   ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    api.GetProcessTimes.restype = wintypes.BOOL
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        raise RelayObserverUnavailable("Edge process cannot be observed")
    try:
        length = wintypes.DWORD(32768); image = ctypes.create_unicode_buffer(length.value)
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if (not api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length))
                or not api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user))):
            raise RelayObserverUnavailable("Edge process identity cannot be read")
        actual = Path(image.value).resolve(strict=True)
        if actual.name.lower() != "msedge.exe" or actual != Path(expected_executable).resolve(strict=True):
            raise PermissionError("CDP process is not the reviewed Edge executable")
        sha = hashlib.sha256()
        checkpoint()
        with actual.open("rb") as source:
            while True:
                checkpoint()
                block = source.read(1024 * 1024)
                if not block:
                    break
                sha.update(block)
        if sha.hexdigest() != expected_sha:
            raise PermissionError("Edge executable changed after operator review")
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        api.CloseHandle(handle)


class _CDP:
    """Private finite observer protocol, no user supplied method or JavaScript."""
    METHODS = {"Browser.getVersion", "Browser.getBrowserCommandLine", "SystemInfo.getProcessInfo",
               "Target.getTargetInfo", "Target.getTargets", "Target.attachToTarget", "Target.detachFromTarget",
               "Page.getFrameTree", "Runtime.evaluate"}

    def __init__(self, endpoint):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise RelayObserverUnavailable("optional websockets observer dependency unavailable") from exc
        checkpoint()
        self.ws = connect(endpoint, open_timeout=4, close_timeout=1, max_size=1_500_000, max_queue=32)
        self.serial = 0

    def call(self, method, params=None, *, session=None):
        if method not in self.METHODS:
            raise PermissionError("CDP command is outside the fixed observer protocol")
        self.serial += 1
        request = {"id": self.serial, "method": method, "params": params or {}}
        if session:
            request["sessionId"] = session
        checkpoint()
        self.ws.send(json.dumps(request, separators=(",", ":")))
        deadline = time.monotonic() + 5
        for _ in range(256):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            checkpoint()
            message = json.loads(self.ws.recv(timeout=remaining))
            if not isinstance(message, dict) or message.get("id") != self.serial:
                continue
            if "error" in message or not isinstance(message.get("result"), dict):
                raise RelayObserverUnavailable("reviewed Edge observer protocol is unavailable")
            return message["result"]
        raise RelayObserverUnavailable("Edge observation deadline exceeded")

    def close(self):
        checkpoint()
        self.ws.close()


class EdgeRelayObservers:
    """Owner/project enrollment and the two exact Canvas server callbacks.

    Enroll/revoke are local HOST APIs with explicit operator approval. They are
    not HTTP/model tools. Configuration, account fingerprints and process pins
    are OS protected in the selected CP, including native PostgreSQL.
    """
    def __init__(self, control, *, clock=time.time):
        self.control, self.store, self.clock = control, control.store, clock
        self.source_path = Path(__file__).with_name("relay_host_reader.js")
        with closing(self.store.connect("provider_content")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS edge_relay_profiles("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,revision INTEGER NOT NULL,enabled INTEGER NOT NULL,"
                "protected_profile TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(owner,project_id))")
            db.execute("CREATE TABLE IF NOT EXISTS edge_relay_observations("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,document_id TEXT NOT NULL,message_id TEXT NOT NULL,"
                "revision INTEGER NOT NULL,fingerprint TEXT NOT NULL,complete INTEGER NOT NULL,"
                "PRIMARY KEY(owner,project_id,document_id,message_id))")

    def enroll(self, *, owner, project_id, browser_ws, target_id, worker, extension_id,
               extension_source_sha256, browser_principal, workspace, user_data_dir, profile_directory,
               executable, reviewed_executable_sha256, reviewed_collector_sha256, expected_account_fingerprint,
               expected_profile_epoch,
               model_bindings, expected_revision=0, operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("operator review of the actual Edge profile/collector is required")
        _endpoint(browser_ws)
        for name, value in {"executable SHA": reviewed_executable_sha256, "collector SHA": reviewed_collector_sha256,
                            "extension SHA": extension_source_sha256, "account fingerprint": expected_account_fingerprint}.items():
            _text(value, name, r"[a-f0-9]{64}")
        for name, value in {"owner":owner,"project":project_id,"target":target_id,"principal":browser_principal,"workspace":workspace}.items():
            _text(value, name)
        _text(worker, "worker", r"TAB-[0-9]{1,12}")
        _text(extension_id, "extension", r"[a-p]{32}")
        _text(expected_profile_epoch, "extension profile generation", r"[A-Za-z0-9_-]{8,160}")
        _text(profile_directory, "profile directory", r"[^/\\:\x00]{1,128}")
        directory = Path(user_data_dir).resolve(strict=True)
        if not directory.is_dir() or any(p.is_symlink() for p in (directory, *directory.parents)):
            raise ValueError("existing reviewed Edge user-data directory required")
        if (not isinstance(model_bindings, dict) or not 1 <= len(model_bindings) <= 64
                or any(not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", str(key))
                       or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value)
                       for key, value in model_bindings.items())):
            raise ValueError("explicit canonical-model to observed-slug bindings required")
        profile = dict(browser_ws=browser_ws,target_id=target_id,worker=worker,extension_id=extension_id,
            extension_source_sha256=extension_source_sha256,browser_principal=browser_principal,workspace=workspace,
            user_data_dir=str(directory),profile_directory=profile_directory,executable=str(Path(executable).resolve(strict=True)),
            executable_sha256=reviewed_executable_sha256,collector_sha256=reviewed_collector_sha256,
            account_fingerprint=expected_account_fingerprint,profile_epoch=expected_profile_epoch,model_bindings=dict(model_bindings))
        self._enrollment(profile)
        snapshot, physical = self._read(profile, {})
        if _account(snapshot) != expected_account_fingerprint:
            raise PermissionError("Edge account differs from the explicitly reviewed identity")
        profile.update(physical)
        with closing(self.store.connect("provider_content")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT revision FROM edge_relay_profiles WHERE owner=? AND project_id=?", (owner, project_id)).fetchone()
            if (old["revision"] if old else 0) != expected_revision:
                raise ValueError("Edge profile enrollment revision changed")
            db.execute("INSERT INTO edge_relay_profiles VALUES(?,?,?,1,?,?) ON CONFLICT(owner,project_id) "
                "DO UPDATE SET revision=excluded.revision,enabled=1,protected_profile=excluded.protected_profile,updated=excluded.updated",
                (owner, project_id, expected_revision + 1, _encode(profile), self.clock()))
        return {"revision":expected_revision + 1,"account_fingerprint":expected_account_fingerprint,"grants_created":False}

    def revoke(self, *, owner, project_id, expected_revision, operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("operator approval required to revoke the Edge binding")
        with closing(self.store.connect("provider_content")) as db, db:
            changed = db.execute("UPDATE edge_relay_profiles SET enabled=0,revision=revision+1,updated=? "
                "WHERE owner=? AND project_id=? AND revision=?", (self.clock(), owner, project_id, expected_revision)).rowcount
            if changed != 1:
                raise ValueError("Edge profile enrollment revision changed")
        return {"revision":expected_revision + 1,"enabled":False,"grants_created":False}

    def _profile(self, owner, project_id):
        with closing(self.store.connect("provider_content")) as db:
            row = db.execute("SELECT * FROM edge_relay_profiles WHERE owner=? AND project_id=? AND enabled=1", (owner,project_id)).fetchone()
        if row is None:
            raise RelayObserverUnavailable("Edge account/profile has not been operator-enrolled")
        return _decode(row["protected_profile"]), row["revision"]

    def _enrollment(self, profile):
        with closing(self.store.connect("chat_access")) as db:
            row = db.execute("SELECT * FROM browser_collectors WHERE extension_id=?", (profile["extension_id"],)).fetchone()
        if (row is None or not row["enabled"] or row["kind"] != "edge"
                or row["source_sha256"] != profile["extension_source_sha256"]
                or row["principal"] != profile["browser_principal"] or row["workspace"] != profile["workspace"]):
            raise PermissionError("Edge collector central enrollment is absent or changed")
        return row["revision"]

    def _read(self, profile, selectors):
        endpoint = _endpoint(profile["browser_ws"])
        checkpoint()
        source = self.source_path.read_bytes()
        if len(source) > 32000 or hashlib.sha256(source).hexdigest() != profile["collector_sha256"]:
            raise PermissionError("independent Edge collector differs from reviewed bytes")
        pid = _listener_pid(endpoint.port)
        started = _process(pid,profile["executable"],profile["executable_sha256"])
        physical = {"pid":pid,"process_started":started}
        if any(key in profile and profile[key] != value for key, value in physical.items()):
            raise PermissionError("Edge process generation changed; operator re-enrollment required")
        peer = _CDP(profile["browser_ws"]); session = None
        try:
            version = peer.call("Browser.getVersion")
            if "Edg/" not in version.get("userAgent", ""):
                raise PermissionError("configured CDP host is not Edge")
            processes = peer.call("SystemInfo.getProcessInfo").get("processInfo", [])
            if len([p for p in processes if p.get("type") == "browser" and p.get("id") == pid]) != 1:
                raise PermissionError("CDP browser differs from the OS listener process")
            arguments = peer.call("Browser.getBrowserCommandLine").get("arguments", [])
            def argument(name, default=None):
                values = []
                for index, value in enumerate(arguments):
                    if value.startswith(name + "="):
                        values.append(value[len(name) + 1:])
                    elif value == name and index + 1 < len(arguments):
                        values.append(arguments[index + 1])
                if len(values) > 1:
                    raise PermissionError("Edge profile command line is ambiguous")
                return values[0] if values else default
            directory = argument("--user-data-dir")
            if (not isinstance(directory, str) or Path(directory).resolve(strict=True) != Path(profile["user_data_dir"])
                    or argument("--profile-directory", "Default") != profile["profile_directory"]):
                raise PermissionError("physical Edge profile differs from the reviewed user-data/profile binding")
            target = peer.call("Target.getTargetInfo", {"targetId":profile["target_id"]})["targetInfo"]
            if target.get("type") != "page" or urlsplit(target.get("url", "")).netloc != "chatgpt.com":
                raise PermissionError("reviewed Edge target is not the ChatGPT page")
            context = target.get("browserContextId", "")
            if "browser_context" in profile and profile["browser_context"] != context:
                raise PermissionError("physical Edge browser context changed")
            physical["browser_context"] = context
            # Profile identity is corroborated inside the physical enrolled
            # extension context. Process command line alone cannot identify
            # every target of a process hosting several profile windows.
            targets = peer.call("Target.getTargets").get("targetInfos", [])
            extension_targets = [row for row in targets if row.get("type") == "service_worker"
                and row.get("url") == "chrome-extension://" + profile["extension_id"] + "/service-worker.js"
                and row.get("browserContextId", "") == context]
            if len(extension_targets) != 1:
                raise RelayObserverUnavailable("physical enrolled Edge extension context is unavailable or ambiguous")
            extension_session = peer.call("Target.attachToTarget", {"targetId":extension_targets[0]["targetId"],"flatten":True})["sessionId"]
            try:
                tab_id = int(profile["worker"].removeprefix("TAB-"))
                # Fixed read-only APIs; no token/session data is requested.
                expression = "(async()=>{const n=" + str(tab_id) + ";const s=await chrome.storage.local.get(['sentra_id_profile_epoch','sentra_id_profile_poison','sentra_id_doc_'+n,'sentra_id_revoke_'+n]);const t=await chrome.tabs.get(n);const m=chrome.runtime.getManifest();return {profile_epoch:s.sentra_id_profile_epoch,poisoned:!!s.sentra_id_profile_poison,revoked:!!s['sentra_id_revoke_'+n],document:s['sentra_id_doc_'+n]||null,url:t.url,extension_id:chrome.runtime.id,source_sha256:m.sentra_source_hash};})()"
                extension_result = peer.call("Runtime.evaluate", {"expression":expression,"returnByValue":True,"awaitPromise":True,"silent":True,"timeout":2500}, session=extension_session)
                lineage = extension_result.get("result", {}).get("value")
                if ("exceptionDetails" in extension_result or not isinstance(lineage, dict)
                        or lineage.get("profile_epoch") != profile["profile_epoch"] or lineage.get("poisoned") or lineage.get("revoked")
                        or lineage.get("extension_id") != profile["extension_id"] or lineage.get("source_sha256") != profile["extension_source_sha256"]
                        or lineage.get("url") != target["url"]):
                    raise PermissionError("physical Edge extension profile/worker differs from the reviewed lineage")
            finally:
                peer.call("Target.detachFromTarget", {"sessionId":extension_session})
            session = peer.call("Target.attachToTarget", {"targetId":profile["target_id"],"flatten":True})["sessionId"]
            before = peer.call("Page.getFrameTree", session=session)["frameTree"]["frame"]
            # The renderer supplies no executable code or expected body. Only
            # durable message selectors enter this fixed source invocation.
            expression = source.decode("utf-8").strip() + "(" + json.dumps(selectors, separators=(",", ":")) + ")"
            result = peer.call("Runtime.evaluate", {"expression":expression,"returnByValue":True,
                "awaitPromise":False,"silent":True,"timeout":2500}, session=session)
            after = peer.call("Page.getFrameTree", session=session)["frameTree"]["frame"]
            if ("exceptionDetails" in result or not before.get("loaderId") or
                    any(before.get(key) != after.get(key) for key in ("id","loaderId","url"))):
                raise RelayObserverUnavailable("Edge physical document changed during observation")
            snapshot = result.get("result", {}).get("value")
            if (not isinstance(snapshot, dict) or snapshot.get("observed") is not True
                    or snapshot.get("url") != after["url"] or urlsplit(after["url"]).scheme != "https"):
                raise RelayObserverUnavailable("reviewed Edge committed UI schema is unavailable")
            if _listener_pid(endpoint.port) != pid or _process(pid,profile["executable"],profile["executable_sha256"]) != started:
                raise PermissionError("Edge OS process changed during observation")
            snapshot["physical_loader_id"] = after["loaderId"]
            snapshot["physical_extension_document"] = lineage.get("document")
            return snapshot, physical
        except (TimeoutError, ConnectionError, OSError, KeyError, ValueError) as exc:
            raise RelayObserverUnavailable("physical Edge observation unavailable") from exc
        finally:
            try:
                if session:
                    peer.call("Target.detachFromTarget", {"sessionId":session})
            finally:
                peer.close()

    def _checked_read(self, owner, project_id, selectors):
        profile, revision = self._profile(owner,project_id)
        enrollment_revision = self._enrollment(profile)
        snapshot, _ = self._read(profile,selectors)
        if _account(snapshot) != profile["account_fingerprint"]:
            raise PermissionError("physical Edge account changed")
        fresh, fresh_revision = self._profile(owner,project_id)
        if fresh_revision != revision or fresh != profile or self._enrollment(profile) != enrollment_revision:
            raise PermissionError("Edge review or collector was revoked during observation")
        return profile, snapshot

    def account_attestor(self, *, control, owner, project_id, message, dot, job):
        if control is not self.control or not all(message.get(key) for key in ("project_id","run_id","work_item_id","operation_id")):
            raise PermissionError("account attestor requires the original shared authority")
        item = control.work_item_info(message["work_item_id"],owner)
        operation = control.durable.operation_status(message["operation_id"],owner)
        run = control.durable.run_status(message["run_id"],owner,include_details=False)
        if (message["project_id"] != project_id or item["run_id"] != run["run_id"] or operation["run_id"] != item["run_id"]
                or item.get("assignee_agent_id") != dot["agent_id"] or job.get("task_id") != message["operation_id"]
                or (job.get("requested_model"),job.get("requested_effort")) != (dot["model"],dot.get("effort"))):
            raise PermissionError("physical account observation has a foreign original turn")
        control.authorization.require(owner,principal_type="agent",principal_id=dot["agent_id"],capability="web:send",
            scope_type="work_item",scope_id=message["work_item_id"],context={"provider":"chatgpt"},local_owner=False)
        profile, snapshot = self._checked_read(owner,project_id,{})
        if profile["workspace"] != run["workspace"] or job.get("leased_worker") != profile["worker"]:
            raise PermissionError("physical Edge differs from the original project/worker")
        if (profile["model_bindings"].get(dot["model"]) != snapshot.get("model_slug")
                or (dot.get("effort") is not None and snapshot.get("effort_observed") is not True)
                or snapshot.get("effort") != dot.get("effort") or snapshot.get("approval_state") == "pending"):
            raise PermissionError("physical Edge model/effort/approval differs from the pinned turn")
        # Re-read live central authority after the bounded external observation.
        control.authorization.require(owner,principal_type="agent",principal_id=dot["agent_id"],capability="web:send",
            scope_type="work_item",scope_id=message["work_item_id"],context={"provider":"chatgpt"},local_owner=False)
        return {"account_verified":True,"requested_model":dot["model"],"requested_effort":dot.get("effort"),
            "worker":profile["worker"],"account_fingerprint":profile["account_fingerprint"],"grants_created":False}

    def assistant_observer(self, **selectors):
        required = {"owner","run_id","job_id","worker","conversation_id","message_id","parent_user_message_id",
                    "revision","body_sha256","identity_epoch","role","state","browser_principal","request_id",
                    "document_id","work_item_id","operation_id","workspace"}
        if set(selectors) != required or selectors["role"] != "assistant" or selectors["state"] not in {"partial","complete"}:
            raise PermissionError("exact scoped assistant selectors required")
        # Project is resolved from the protected ORIGINAL shell turn, not from
        # a renderer job or an Electron browser descriptor.
        with closing(self.store.connect("shell")) as db:
            turn = db.execute("SELECT * FROM canvas_shell_web_turns WHERE owner=? AND operation_id=? AND job_id=?",
                (selectors["owner"],selectors["operation_id"],selectors["job_id"])).fetchone()
        if turn is None:
            raise PermissionError("assistant has no original shell turn")
        project = turn["project_id"]
        profile, snapshot = self._checked_read(selectors["owner"],project,{key:selectors[key] for key in
            ("message_id","parent_user_message_id","request_id","conversation_id")})
        if ((profile["worker"],profile["browser_principal"],profile["workspace"],snapshot.get("document_id"),snapshot.get("conversation_id")) !=
                (selectors["worker"],selectors["browser_principal"],selectors["workspace"],selectors["document_id"],selectors["conversation_id"])):
            raise PermissionError("assistant physical profile/document differs from original proof")
        document = snapshot.get("physical_extension_document")
        if (not isinstance(document,dict) or any(document.get(key) != selectors[key] for key in ("worker","document_id","identity_epoch"))
                or document.get("profile_epoch") != profile["profile_epoch"] or document.get("observed") is not True
                or document.get("route") != selectors["conversation_id"]):
            raise PermissionError("assistant extension document lineage differs from its physical Edge context")
        from native_bridge.web_evidence_ingress import AuthenticatedWebReceiptBroker
        AuthenticatedWebReceiptBroker(self.control,None).prove_message(owner=selectors["owner"],run_id=selectors["run_id"],
            browser_principal=selectors["browser_principal"],request_id=selectors["request_id"],worker=selectors["worker"],
            conversation_id=selectors["conversation_id"],message_id=selectors["parent_user_message_id"],
            extension_id=profile["extension_id"],document_id=selectors["document_id"],identity_epoch=selectors["identity_epoch"])
        messages = {row["message_id"]:row for row in snapshot.get("messages",[])}
        parent, child = messages.get(selectors["parent_user_message_id"]), messages.get(selectors["message_id"])
        if (snapshot.get("assistant_children") != [selectors["message_id"]]
                or not parent or not child or parent["role"] != "user" or parent["request_id"] != selectors["request_id"]
                or child["role"] != "assistant" or child["parent_id"] != parent["message_id"]
                or type(child["complete"]) is not bool or child["complete"] != (selectors["state"] == "complete")
                or hashlib.sha256(child["body"].encode()).hexdigest() != selectors["body_sha256"]):
            raise PermissionError("independent committed assistant body/parent/role/state differs")
        fingerprint = _digest({"body":selectors["body_sha256"],"parent":parent["message_id"],"state":selectors["state"],
            "loader":snapshot["physical_loader_id"],"process":profile["process_started"],"epoch":selectors["identity_epoch"],
            "collector":profile["collector_sha256"]})
        with closing(self.store.connect("provider_content")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM edge_relay_observations WHERE owner=? AND project_id=? AND document_id=? AND message_id=?",
                (selectors["owner"],project,selectors["document_id"],selectors["message_id"])).fetchone()
            if old and old["complete"] and old["fingerprint"] != fingerprint:
                raise PermissionError("independent final observation cannot be replaced")
            revision = old["revision"] if old and old["fingerprint"] == fingerprint else (old["revision"] + 1 if old else 1)
            db.execute("INSERT INTO edge_relay_observations VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,project_id,document_id,message_id) "
                "DO UPDATE SET revision=excluded.revision,fingerprint=excluded.fingerprint,complete=excluded.complete",
                (selectors["owner"],project,selectors["document_id"],selectors["message_id"],revision,fingerprint,int(child["complete"])))
        return {**selectors,"authenticated":True,"host_observation":{"revision":revision,"body_sha256":selectors["body_sha256"],
            "state":selectors["state"],"collector_id":"edge-cdp-" + _digest([profile["worker"],profile["target_id"]])[:32],
            "source_sha256":profile["collector_sha256"],"document_id":selectors["document_id"],"identity_epoch":selectors["identity_epoch"]}}

    def availability(self, *, owner, project_id):
        """Configuration availability only; no I/O probe or model delivery claim."""
        try:
            profile, _ = self._profile(owner,project_id)
            self._enrollment(profile)
            import importlib.util
            source = self.source_path.read_bytes()
            if hashlib.sha256(source).hexdigest() != profile["collector_sha256"]:
                raise PermissionError("independent Edge collector review changed")
            try:
                dependency = importlib.util.find_spec("websockets.sync.client") is not None
            except (ImportError,ModuleNotFoundError):
                dependency = False
            ready = os.name == "nt" and dependency
            return {"model_delivery_available":ready,"proves_model_delivery":False,
                "model_delivery_reason":None if ready else "edge_observer_dependency_or_os_unavailable",
                "physical_observation_required_each_send":True}
        except (RelayObserverUnavailable,PermissionError,ValueError,OSError):
            return {"model_delivery_available":False,"proves_model_delivery":False,"model_delivery_reason":"edge_profile_review_not_configured"}
