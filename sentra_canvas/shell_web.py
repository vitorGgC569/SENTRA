"""Single-turn binary relay composition; all authority is borrowed from the CP.

The host installs a calibrated live account attestor. JSON configuration and
extension receipts alone cannot substitute that proof. Interrupted submissions
are observed again, never admitted or sent again.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import threading
import time

from sentra_core.conversations import _encode, _decode
from .shell_optional import UNVERIFIED_TURN_MODEL, UNVERIFIED_TURN_REASON
from .store import Denied


class UnverifiedTurn(RuntimeError):
    """A listed model was not submitted. Callers must not retry or fall through."""


class ShellWebRuntime:
    def __init__(self, runtime):
        self.runtime, self.control, self.canvas = runtime, runtime.control, runtime.canvas
        self.owner = runtime.owner
        self.lock = threading.RLock()
        self.relay = None
        self.account_attestor = None
        self.assistant_observer = None
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_web_turns("
                "operation_id TEXT PRIMARY KEY,owner TEXT NOT NULL,project_id TEXT NOT NULL,"
                "conversation_id TEXT NOT NULL,protected_turn TEXT NOT NULL,job_id TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_web_conversations("
                "owner TEXT NOT NULL,project_id TEXT NOT NULL,conversation_id TEXT NOT NULL,"
                "remote_conversation_id TEXT NOT NULL,PRIMARY KEY(owner,project_id,conversation_id))")

    def attach_observers(self, *, account_attestor, assistant_observer):
        if not callable(account_attestor) or not callable(assistant_observer):
            raise ValueError("independent calibrated account and assistant host observers required")
        with self.lock:
            if self.relay is not None:
                raise RuntimeError("relay observers cannot change while its listener is running")
            self.account_attestor, self.assistant_observer = account_attestor, assistant_observer

    def availability(self):
        config = self.canvas._shell_configuration.get("web_relay", {})
        configured = isinstance(config, dict) and config.get("enabled") is True
        ready = configured and callable(self.account_attestor) and callable(self.assistant_observer)
        return {"model_delivery_available": ready, "proves_model_delivery": False,
            "model_delivery_reason": None if ready else (
                "relay_account_attestor_not_composed" if configured else "binary_relay_not_configured")}

    def _configuration(self):
        config = self.canvas._shell_configuration.get("web_relay", {})
        if not isinstance(config, dict) or set(config) - {"enabled", "extension_dir", "token_file", "port", "models"}:
            raise ValueError("invalid trusted Web relay configuration")
        if config.get("enabled") is not True or not callable(self.account_attestor) or not callable(self.assistant_observer):
            raise RuntimeError(self.availability()["model_delivery_reason"])
        models = config.get("models")
        if not isinstance(models, list) or not 1 <= len(models) <= 64 or any(
                not isinstance(model, str) or not 1 <= len(model) <= 128 for model in models):
            raise ValueError("host reviewed relay model names required")
        port = config.get("port", 8765)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("fixed loopback relay port required")
        return config

    def owns_conversation(self, project_id, conversation_id):
        with closing(self.control.store.connect("shell")) as db:
            return db.execute("SELECT 1 FROM canvas_shell_web_conversations WHERE owner=? "
                "AND project_id=? AND conversation_id=?", (self.owner, project_id, conversation_id)).fetchone() is not None

    def grants(self, message, dot):
        config = self._configuration()
        if dot["model"] not in config["models"]:
            raise Denied("admitted model is outside the host reviewed relay models")
        grant = self.control.authorization.require(self.owner, principal_type="agent",
            principal_id=dot["agent_id"], capability="web:send", scope_type="work_item",
            scope_id=message["work_item_id"], context={"provider": "chatgpt"}, local_owner=False)
        if message.get("attachments"):
            self.control.authorization.require(self.owner, principal_type="agent",
                principal_id=dot["agent_id"], capability="web:attach", scope_type="work_item",
                scope_id=message["work_item_id"], context={"provider": "chatgpt"}, local_owner=False)
        return grant

    def _live_account(self, binding, job):
        with closing(self.control.store.connect("shell")) as db:
            row = db.execute("SELECT protected_turn FROM canvas_shell_web_turns WHERE operation_id=? "
                "AND owner=?", (binding["operation_id"], self.owner)).fetchone()
        if row is None or not callable(self.account_attestor):
            raise Denied("relay has no calibrated original turn binding")
        turn = _decode(row["protected_turn"])
        message, dot = turn["message"], turn["dot"]
        self.grants(message, dot)
        actor = self.control.durable.agent_info(dot["agent_id"], self.owner)
        if actor["run_id"] != message["run_id"] or actor["desired_state"] == "WAITING":
            raise Denied("relay agent was paused or moved to another Run")
        observed = self.account_attestor(control=self.control, owner=self.owner,
            project_id=message["project_id"], message=message, dot=dot, job=job)
        if not isinstance(observed, dict) or observed.get("account_verified") is not True or (
                observed.get("requested_model"), observed.get("requested_effort")) != (dot["model"], dot.get("effort")):
            raise Denied("physical relay account/model/effort is not attested for this turn")

    def _service(self):
        with self.lock:
            if self.relay is None:
                from native_bridge.relay import RelayServer
                config = self._configuration()
                directory = Path(config["extension_dir"]).resolve(strict=True)
                token_file = Path(config["token_file"]).resolve(strict=True)
                if not directory.is_dir() or token_file.stat().st_size > 512:
                    raise ValueError("bounded host relay token and extension directory required")
                token = token_file.read_text(encoding="utf-8").strip()
                outbox = self.canvas.state_dir.parent / "browser" / "relay.sqlite3"
                outbox.parent.mkdir(parents=True, exist_ok=True)
                relay = RelayServer(port=config.get("port", 8765), extension_dir=directory,
                    token=token, db_path=outbox, authenticated_control=self.control,
                    assistant_observer=self.assistant_observer)
                original_progress = relay.state.progress
                def progress(job_id, worker, lease_token, phase):
                    if phase == "sending":
                        bound = relay.state.web_send.binding(job_id)
                        if bound is not None:
                            self._live_account(bound, relay.state.leased_payload(job_id, worker, lease_token))
                    return original_progress(job_id, worker, lease_token, phase)
                relay.state.progress = progress
                self.relay = relay.start()
            return self.relay.state

    def execute(self, message, dot):
        if dot.get("model") == UNVERIFIED_TURN_MODEL:
            raise UnverifiedTurn(UNVERIFIED_TURN_REASON)
        from native_bridge.shell_multimodal import dispatch_shell_turn
        from sentra_mcp.services.web_history_assets import WebAssetDrafts
        grant = self.grants(message, dot)
        oid = message["operation_id"]
        workspace = self.runtime._project(message["project_id"], self.owner)
        with closing(self.control.store.connect("shell")) as db, db:
            previous = db.execute("SELECT * FROM canvas_shell_web_turns WHERE operation_id=?", (oid,)).fetchone()
            remote = db.execute("SELECT remote_conversation_id FROM canvas_shell_web_conversations "
                "WHERE owner=? AND project_id=? AND conversation_id=?",
                (self.owner, message["project_id"], message["conversation_id"])).fetchone()
            if previous is None and remote is None and self.runtime._journal_messages(message["conversation_id"]):
                raise Denied("existing CLI conversation needs an explicit relay continuation before binary dispatch")
            if previous is None:
                db.execute("INSERT INTO canvas_shell_web_turns VALUES(?,?,?,?,?,NULL)",
                    (oid, self.owner, message["project_id"], message["conversation_id"], _encode({"message": message, "dot": dot})))
        if previous is not None:
            # A reserved turn might already have crossed its physical fence.
            return self.observe(message, dot)
        relay = self._service()
        conversation = {"space_id": message["space_id"], "conversation_id": message["conversation_id"]}
        resolved = self.runtime.optional.attachment_bytes(message["project_id"], self.owner,
            conversation, message.get("attachments", []))
        attachments = [{**descriptor, "attachment_id": ref, "data": data}
            for ref, (descriptor, data) in zip(message.get("attachments", []), resolved)]
        key = "shell-web-" + hashlib.sha256((self.owner + "\0" + oid).encode()).hexdigest()
        resource = "shell-web-" + hashlib.sha256((self.owner + "\0" + message["conversation_id"]).encode()).hexdigest()
        lease = self.control.durable.acquire_lease(message["run_id"], self.owner, resource,
            operation_id=oid, ttl_s=240)
        try:
            budget = self.control.budgets.reserve_quota(self.owner, event_id=key,
                workspace=workspace["path"], run_id=message["run_id"], work_item_id=message["work_item_id"],
                operation_id=oid, agent_id=dot["agent_id"], provider="chatgpt")
            if not budget["allowed"]:
                raise Denied("relay turn blocked by central budget")
            self.control.durable.update_operation(oid, self.owner, state="RUNNING",
                resource_key=resource, fencing_token=lease["fencing_token"], event_type="SHELL_BINARY_RELAY_RUNNING")
            from .shell_goals import goal_context
            goal = goal_context(self.control, self.owner, message["conversation_id"])
            prompt = message["content"]
            if goal:
                prompt = "Objetivo ativo desta conversa (contexto de trabalho):\n" + goal["objective"] + "\n\nMensagem do usuário:\n" + prompt
            result = dispatch_shell_turn(self.control, relay, WebAssetDrafts(self.control), relay.web_send,
                owner=self.owner, run_id=message["run_id"], work_item_id=message["work_item_id"],
                operation_id=oid, principal_id=dot["agent_id"], grant_id=grant["grant_id"],
                workspace=workspace["path"], project_id=message["project_id"], space_id=message["space_id"],
                conversation_id=message["conversation_id"], request_identity=key, prompt=prompt,
                conversation_url="https://chatgpt.com/c/" + remote["remote_conversation_id"] if remote else None,
                attachments=attachments, operator_approved=True,
                requested_model=dot["model"], requested_effort=dot.get("effort"))
            job_id = result["intent"]["job_id"]
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("UPDATE canvas_shell_web_turns SET job_id=? WHERE operation_id=?", (job_id, oid))
            return self._wait_for_answer(message, dot, relay, job_id, resource, lease)
        finally:
            self.control.durable.release_lease(resource, self.owner, lease["fencing_token"])

    def _wait_for_answer(self, message, dot, relay, job_id, resource, lease):
        from .shell_runtime import SHELL_PROVIDER_TIMEOUT_SECONDS
        deadline = time.monotonic() + SHELL_PROVIDER_TIMEOUT_SECONDS
        renew_at = time.monotonic() + 60
        while not self.runtime._stop.is_set() and time.monotonic() < deadline:
            operation = self.control.durable.operation_status(message["operation_id"], self.owner)
            run = self.control.durable.run_status(message["run_id"], self.owner, include_details=False)
            if operation["state"] == "CANCEL_REQUESTED" or run["state"] != "RUNNING":
                relay.web_send.failure(self.owner, job_id, reason="shell authority interrupted")
                return None
            if time.monotonic() >= renew_at:
                self.control.durable.renew_lease(resource, self.owner, lease["fencing_token"], ttl_s=240)
                renew_at = time.monotonic() + 60
            status = self.observe(message, dot)
            if status is not None:
                return status
            self.runtime._stop.wait(.25)
        return None

    def observe(self, message, dot):
        """Read an original final only; never call admit, claim, or Send."""
        relay = self._service()
        with closing(self.control.store.connect("session_checkpoint")) as db:
            rows = db.execute("SELECT job_id FROM web_send_intents WHERE owner=? AND operation_id=?",
                (self.owner, message["operation_id"])).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise Denied("shell Operation has ambiguous physical sends")
        job_id = rows[0]["job_id"]
        status = relay.web_send.status(self.owner, job_id)
        if status["state"] != "ANSWERED" or not status["collector_message_attested"]:
            return None
        from native_bridge.web_generated_assets import WebGeneratedAssets
        receipt = (status.get("delivery") or {}).get("receipt")
        if not receipt or not WebGeneratedAssets(self.control).ready_for_job(
                owner=self.owner,job_id=job_id,conversation_id=receipt["conversation_id"],
                message_id=status["answer_message_id"]):
            return None  # never publish a final before its declared native bytes
        result = relay.result(job_id)
        receipt = (status.get("delivery") or {}).get("receipt")
        if not result or result.get("status") != "COMPLETED" or not isinstance(receipt, dict):
            return None
        if (result.get("task_id"), result.get("conversation_id")) != (
                message["operation_id"], receipt.get("conversation_id")):
            raise Denied("relay answer scope differs from original receipt")
        content = result.get("result")
        if not isinstance(content, str) or not status.get("answer_message_id"):
            raise Denied("relay has no exact final assistant body")
        with closing(self.control.store.connect("shell")) as db, db:
            old = db.execute("SELECT remote_conversation_id FROM canvas_shell_web_conversations "
                "WHERE owner=? AND project_id=? AND conversation_id=?",
                (self.owner, message["project_id"], message["conversation_id"])).fetchone()
            if old is not None and old["remote_conversation_id"] != receipt["conversation_id"]:
                raise Denied("relay conversation changed during completion")
            db.execute("INSERT INTO canvas_shell_web_conversations VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                (self.owner, message["project_id"], message["conversation_id"], receipt["conversation_id"]))
        return {"content": content, "receipt_id": "web:" + job_id + ":" + status["answer_message_id"],
            "web_job_id": job_id, "web_answer_message_id": status["answer_message_id"],
            "web_answer_revision": status["answer_revision"], "web_attested_final": True}

    def close(self):
        with self.lock:
            if self.relay is not None:
                self.relay.stop()
                self.relay = None
