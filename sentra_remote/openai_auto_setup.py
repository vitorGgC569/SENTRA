"""Installer-authorized enrollment, bounded UI automation and verified storage."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
import threading
from typing import Any, Callable

from .product import ProductPaths, configure_tunnel, tunnel_credential_storage, tunnel_key_update
from .secrets import protect_secret, unprotect_secret


class CredentialProtectionUnavailable(RuntimeError):
    """Fixed failure without OS/provider diagnostics that could contain a secret."""


def verify_credential_protection() -> None:
    """Prove the current OS user can protect and recover a disposable probe."""
    probe = "sentra-setup-" + uuid.uuid4().hex
    try:
        protected = protect_secret(probe)
        try:
            if unprotect_secret(protected) != probe:
                raise RuntimeError("protection round-trip failed")
        finally:
            if protected.startswith("keyring:"):
                import keyring
                keyring.delete_password("SENTRA Commander", protected[len("keyring:"):])
    except Exception:
        raise CredentialProtectionUnavailable("credential_protection_unavailable") from None


def run_setup_enrollment(paths: ProductPaths, notify: Callable, *, timeout_s: float = 650) -> dict:
    """Keep enrollment in Setup, with verified recovery before browser effects."""
    # Repeat immediately before account effects; pre-install success may be old.
    try:
        verify_credential_protection()
    except CredentialProtectionUnavailable:
        return {"ok": False, "reason": "credential_protection_unavailable"}
    from .local_runtime import LocalRuntime
    from .product import ProductSettings
    runtime = LocalRuntime(paths, ProductSettings.load(paths.settings))
    recovered = recover_enrollment(paths, runtime)
    if recovered.get("ok"):
        return recovered
    if not recovered.get("enrollment_needed"):
        return {"ok": False, "reason": "manual_recovery_required"}
    from .openai_browser_enrollment import OpenAIConsentBrowser
    closed = threading.Event()
    result = {"ok": False, "reason": "browser_enrollment_incomplete"}

    def on_event(event: str, message: str) -> None:
        if event == "ready":
            result.update(ok=True, reason="tunnel_verified")
        elif event == "attention":
            known = {"browser_account_selection_required", "login_required",
                     "browser_extension_required", "browser_enrollment_already_running",
                     "all_permissions_unavailable", "platform_ui_needs_attention",
                     "chatgpt_workspace_required", "workspace_association_unverified",
                     "manual_recovery_required", "tunnel_verification_failed"}
            result.update(ok=False, reason=message if message in known else "browser_enrollment_needs_attention")
        elif event == "closed":
            closed.set()
        # The tunnel identifier is not needed by Setup; all credentials stay
        # within enrollment and Windows-protected product storage.
        if event != "tunnel":
            notify(event, message)

    session = OpenAIConsentBrowser(paths, on_event, runtime=runtime)
    session.start(approved=True, automatic=True)
    if not closed.wait(timeout_s):
        session.close()
        return {"ok": False, "reason": "browser_enrollment_timeout"}
    return result


def edge_automation_profile(state_dir) -> Path:
    """Empty Edge profile for installer automation. Never the signed-in Edge user."""
    from pathlib import Path
    profile = (Path(state_dir) / "edge-automation").resolve()
    local = os.environ.get("LOCALAPPDATA", "")
    signed_in = (Path(local) / "Microsoft" / "Edge" / "User Data").resolve() if local else None
    if signed_in is not None and (profile == signed_in or signed_in in profile.parents):
        raise ValueError("automation browser must not use the signed-in Edge profile")
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def authorize_installer_enrollment(paths: ProductPaths) -> None:
    """Persist the installer checkbox authorization for one Desktop handoff."""
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "version": 1, "install_dir": str(paths.install_dir.resolve()),
        "expires": time.time() + 1800, "permissions": "All",
    })
    target = paths.state_dir / "openai-enrollment-consent"
    staged = target.with_suffix(".tmp")
    staged.write_text(protect_secret(payload), encoding="utf-8")
    staged.replace(target)


def consume_installer_enrollment(paths: ProductPaths) -> bool:
    target = paths.state_dir / "openai-enrollment-consent"
    try:
        # Atomic claim prevents two Desktop processes from using one consent.
        claim = target.with_name(target.name + "." + uuid.uuid4().hex)
        target.rename(claim)
    except FileNotFoundError:
        return False
    try:
        encrypted = claim.read_text(encoding="utf-8")
        if not encrypted.startswith("dpapi:" if os.name == "nt" else "keyring:"):
            return False
        data = json.loads(unprotect_secret(encrypted))
        return bool(
            data.get("version") == 1 and data.get("permissions") == "All"
            and time.time() <= float(data["expires"])
            and os.path.normcase(data["install_dir"])
            == os.path.normcase(str(paths.install_dir.resolve()))
        )
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False
    finally:
        claim.unlink(missing_ok=True)


def _verified_tunnel(verdict: dict) -> bool:
    health = verdict.get("status") or {}
    return bool(verdict.get("chatgpt_onboarding", {}).get("ready") is True
                and health.get("mcp", {}).get("ok") is True
                and health.get("tunnel", {}).get("ok") is True
                and not health.get("tunnel", {}).get("reauth_required"))


def _protected_config(raw: bytes) -> bool:
    """Validate recovery bytes without returning or logging a plaintext key."""
    from .openai_browser_enrollment import TUNNEL_PATTERN, RUNTIME_KEY_PATTERN
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return False
        protected = data.get("runtime_key")
        if not isinstance(protected, str) or not protected.startswith(
            "dpapi:" if os.name == "nt" else "keyring:"
        ):
            return False
        return bool(TUNNEL_PATTERN.fullmatch(str(data.get("tunnel_id") or ""))
                    and RUNTIME_KEY_PATTERN.fullmatch(unprotect_secret(protected)))
    except Exception:
        return False


def remember_enrollment_tunnel(paths: ProductPaths, tunnel_id: str, *, name: str = "") -> None:
    """Retain only the selected resource ID for an authorized retry, never a key."""
    from .openai_browser_enrollment import TUNNEL_PATTERN
    if not TUNNEL_PATTERN.fullmatch(tunnel_id):
        raise ValueError("tunnel_not_found")
    if name and not re.fullmatch(r"SENTRA-[0-9a-f]{10}", name):
        raise ValueError("saved_tunnel_not_visible")
    protected = protect_secret(json.dumps({"version": 1,
        "install_dir": str(paths.install_dir.resolve()), "tunnel_id": tunnel_id, "name": name}))
    if os.name == "nt" and not protected.startswith("dpapi:"):
        raise RuntimeError("credential_protection_unavailable")
    target = paths.state_dir / "openai-enrollment-tunnel.dpapi"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(protected)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def remembered_enrollment_tunnel(paths: ProductPaths) -> str:
    """A checkpoint supplies no consent and is bound to this Windows user/install."""
    return _remembered_enrollment_tunnel(paths).get("tunnel_id", "")


def remembered_enrollment_tunnel_name(paths: ProductPaths, tunnel_id: str) -> str:
    data = _remembered_enrollment_tunnel(paths)
    return data.get("name", "") if data.get("tunnel_id") == tunnel_id else ""


def _remembered_enrollment_tunnel(paths: ProductPaths) -> dict:
    from .openai_browser_enrollment import TUNNEL_PATTERN
    target = paths.state_dir / "openai-enrollment-tunnel.dpapi"
    if not target.exists():
        return {}
    try:
        if target.is_symlink() or target.stat().st_size > 16384:
            raise ValueError()
        protected = target.read_text(encoding="utf-8")
        if os.name == "nt" and not protected.startswith("dpapi:"):
            raise ValueError()
        data = json.loads(unprotect_secret(protected))
        identifier = data.get("tunnel_id")
        if (data.get("version") != 1
                or data.get("install_dir") != str(paths.install_dir.resolve())
                or not isinstance(identifier, str) or not TUNNEL_PATTERN.fullmatch(identifier)
                or not isinstance(data.get("name", ""), str)
                or (data.get("name") and not re.fullmatch(r"SENTRA-[0-9a-f]{10}", data["name"]))):
            raise ValueError()
        return data
    except Exception:
        raise ValueError("manual_recovery_required") from None


def clear_remembered_enrollment_tunnel(paths: ProductPaths, tunnel_id: str) -> None:
    if remembered_enrollment_tunnel(paths) == tunnel_id:
        (paths.state_dir / "openai-enrollment-tunnel.dpapi").unlink(missing_ok=True)


def recover_enrollment(paths: ProductPaths, runtime: Any) -> dict:
    """Resolve interrupted storage and reuse credentials before browser creation."""
    try:
        with tunnel_key_update(paths):
            return _recover_enrollment(paths, runtime)
    except Exception:
        # Storage/runtime exceptions may carry credentials. Only expose a code.
        return {"ok": False, "reason": "manual_recovery_required"}


def _recover_enrollment(paths: ProductPaths, runtime: Any) -> dict:
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    blocked = {"ok": False, "reason": "manual_recovery_required"}
    if paths.tunnel_config.with_name("tunnel.json.rotation-rollback").exists():
        return blocked
    current = paths.tunnel_config.read_bytes() if paths.tunnel_config.exists() else None
    original = backup.read_bytes() if backup.exists() else None
    if current is None and original in (None, b""):
        backup.unlink(missing_ok=True)
        return {"ok": False, "enrollment_needed": True}

    # A crash after saving may already have committed working credentials.
    # Verify these first so retries do not rotate a key or create a new tunnel.
    if current is not None and _protected_config(current):
        try:
            if _verified_tunnel(runtime.connect_and_verify(timeout_s=30.0)):
                backup.unlink(missing_ok=True)
                return {"ok": True, "tunnel_verified": True, "credentials_reused": True}
        except Exception:
            pass
    if not original or not _protected_config(original):
        return blocked

    # Do not overwrite configuration while an existing client cannot be stopped.
    running = bool(runtime.status().get("tunnel", {}).get("ok"))
    if not runtime.stop("tunnel") and running:
        return blocked
    staged = paths.tunnel_config.with_suffix(".restore")
    with staged.open("wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    staged.replace(paths.tunnel_config)
    if not _verified_tunnel(runtime.connect_and_verify(timeout_s=30.0)):
        return blocked
    backup.unlink()
    return {"ok": True, "tunnel_verified": True, "credentials_reused": True,
            "rollback_restored": True}


def configure_and_verify(paths: ProductPaths, tunnel_id: str, key: str, runtime: Any) -> dict:
    with tunnel_key_update(paths):
        if paths.tunnel_config.with_name("tunnel.json.enrollment-rollback").exists():
            try:
                recovered = _recover_enrollment(paths, runtime)
            except Exception:
                return {"ok": False, "reason": "manual_recovery_required"}
            if not recovered.get("enrollment_needed"):
                return recovered
        return _configure_and_verify(paths, tunnel_id, key, runtime)


def _configure_and_verify(paths: ProductPaths, tunnel_id: str, key: str, runtime: Any) -> dict:
    """Keep an encrypted recovery copy until the authenticated tunnel is ready."""
    from .openai_browser_enrollment import _single_identifier, TUNNEL_PATTERN, RUNTIME_KEY_PATTERN
    _single_identifier([tunnel_id], TUNNEL_PATTERN, label="tunnel")
    _single_identifier([key], RUNTIME_KEY_PATTERN, label="new_key")
    backup = paths.tunnel_config.with_name("tunnel.json.enrollment-rollback")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    original = paths.tunnel_config.read_bytes() if paths.tunnel_config.exists() else None
    if original is not None and not tunnel_credential_storage(paths).get("ok"):
        raise ValueError("prior_credential_storage_needs_repair")
    if paths.tunnel_config.with_name("tunnel.json.rotation-rollback").exists():
        raise RuntimeError("prior incomplete rotation requires recovery")
    # Exclusive creation also serializes enrollment/rotation in this installation.
    with backup.open("xb") as stream:
        stream.write(original or b"")
        stream.flush()
        os.fsync(stream.fileno())
    stopped = False
    changed = False
    running_before = False
    try:
        running_before = bool(runtime.status().get("tunnel", {}).get("ok"))
        stopped = bool(runtime.stop("tunnel"))
        if running_before and not stopped:
            raise RuntimeError("prior_tunnel_stop_failed")
        configure_tunnel(paths, tunnel_id, key)
        changed = True
        if not tunnel_credential_storage(paths).get("ok"):
            raise RuntimeError("credential_storage_failed")
        verdict = runtime.connect_and_verify(timeout_s=30.0)
        if not _verified_tunnel(verdict):
            raise RuntimeError("tunnel_verification_failed")
        backup.unlink()
        return {"ok": True, "tunnel_verified": True}
    except Exception:
        try:
            if changed:
                runtime.stop("tunnel")
            if original is None:
                paths.tunnel_config.unlink(missing_ok=True)
            else:
                staged = paths.tunnel_config.with_suffix(".restore")
                staged.write_bytes(original)
                staged.replace(paths.tunnel_config)
            if stopped and (running_before or original is not None):
                runtime.connect_and_verify(timeout_s=30.0)
            restored = (not running_before or bool(runtime.status().get("tunnel", {}).get("ok")))
            if restored:
                backup.unlink()
        except Exception:
            restored = False
        return {"ok": False, "rollback_restored": restored,
                "reason": "tunnel_verification_failed", "manual_recovery_available": backup.exists()}


class AutomaticEnrollment:
    """Create through visible official UI; login stays in the user's browser."""

    def __init__(self, page: Any, notify: Callable, cancelled: Any, *, existing_tunnel_id: str = "",
                 existing_tunnel_name: str = "",
                 on_tunnel_selected: Callable[[str], None] | None = None) -> None:
        self.page, self.notify, self.cancelled = page, notify, cancelled
        self.name = "SENTRA-" + uuid.uuid4().hex[:10]
        self.existing_tunnel_id = existing_tunnel_id
        self.existing_tunnel_name = existing_tunnel_name
        self.on_tunnel_selected = on_tunnel_selected

    def guard(self, kind: str) -> None:
        from .openai_browser_enrollment import _trusted_platform_location
        if self.cancelled.is_set() or self.page.is_closed():
            raise RuntimeError("enrollment_cancelled")
        if not _trusted_platform_location(self.page.url, kind=kind):
            raise ValueError("open_official_" + ("tunnels" if kind == "tunnel" else "api_keys") + "_page")

    def wait(self, probe: Callable, *, kind: str, timeout: float = 30) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.guard(kind)
            association_error = self.page.get_by_text(re.compile(
                r"Não foi possível verificar automaticamente a associação|"
                r"(?:unable to|could not|cannot|couldn't) (?:automatically )?verify.*(?:workspace|association)", re.I
            ))
            if association_error.count() and association_error.first.is_visible():
                raise ValueError("workspace_association_unverified")
            result = probe()
            if result is not None:
                return result
            self.page.wait_for_timeout(200)
        raise ValueError("platform_ui_needs_attention")

    def button(self, scope: Any, names: str) -> Any:
        items = scope.get_by_role("button", name=re.compile(names, re.I))
        visible = [items.nth(i) for i in range(items.count()) if items.nth(i).is_visible()]
        return visible[0] if len(visible) == 1 and visible[0].is_enabled() else None

    def click(self, scope: Any, names: str, kind: str) -> None:
        button = self.wait(lambda: self.button(scope, names), kind=kind)
        self.guard(kind)
        button.click(timeout=5000)

    def dialog(self, kind: str) -> Any:
        def find():
            dialogs = self.page.locator('[role="dialog"]:visible, [aria-modal="true"]:visible')
            return dialogs.first if dialogs.count() == 1 else None
        return self.wait(find, kind=kind)

    def name_dialog(self, dialog: Any, kind: str) -> None:
        field = dialog.get_by_role("textbox", name=re.compile(r"name|nome", re.I))
        if field.count() == 0:
            field = dialog.locator('input:not([type="hidden"]):not([readonly]):not([aria-hidden="true"]):visible')
        if field.count() != 1:
            raise ValueError("platform_ui_needs_attention")
        self.guard(kind)
        field.fill(self.name, timeout=5000)

    def associate_workspace(self, dialog: Any) -> None:
        """Do not create a ChatGPT tunnel with only a Platform organization."""
        choose = dialog.get_by_role("button", name=re.compile(
            r"^(?:Search workspaces by name or ID|Pesquisar workspaces por nome ou ID)$", re.I
        ))
        if choose.count() == 0:
            # A preselected workspace or older form has no empty selector.
            return
        element_id = choose.get_attribute("id")
        if not element_id:
            raise ValueError("chatgpt_workspace_required")
        selector = dialog.locator("[id=" + json.dumps(element_id) + "]")
        self.guard("tunnel")
        choose.click(timeout=5000)
        options = self.page.get_by_role("option").filter(visible=True)
        # A sole discoverable workspace can be selected without guessing IDs.
        if options.count() == 1 and not re.search(r"exact ID|ID exato", options.inner_text(), re.I):
            self.guard("tunnel")
            options.click(timeout=5000)
            selector.press("Escape", timeout=5000)
        else:
            selector.press("Escape", timeout=5000)
            self.notify("workspace_required", "Choose the ChatGPT workspace in the tunnel form. Automatic setup resumes after selection.")
        try:
            self.wait(lambda: True if not re.search(r"Search workspaces|Pesquisar workspaces", selector.inner_text(), re.I) else None,
                      kind="tunnel", timeout=600)
        except ValueError as exc:
            if str(exc) == "platform_ui_needs_attention":
                raise ValueError("chatgpt_workspace_required") from None
            raise

    @staticmethod
    def native_option_labels(selector: Any, *, enabled_only: bool = False) -> list[str]:
        options = selector.locator("option:not([disabled])" if enabled_only else "option")
        return [options.nth(i).inner_text().strip() for i in range(options.count())]

    @staticmethod
    def native_selected_label(selector: Any) -> str:
        selected = selector.locator("option:checked")
        return selected.inner_text().strip() if selected.count() == 1 else ""

    def select_native_project(self, dialog: Any) -> bool:
        placeholder = re.compile(r"^(?:Select project|Selecionar projeto)[\s.…]*$", re.I)
        defaults = re.compile(r"^(?:Default project|Projeto padrão)$", re.I)
        selectors = dialog.locator("select:visible")
        candidates = [selectors.nth(i) for i in range(selectors.count())
                      if any(placeholder.fullmatch(text) for text in self.native_option_labels(selectors.nth(i)))]
        if not candidates:
            return False
        if len(candidates) != 1:
            raise ValueError("project_selection_required")
        selector = candidates[0]
        def choice():
            if not selector.is_enabled():
                return None
            labels = [text for text in self.native_option_labels(selector, enabled_only=True)
                      if text and not placeholder.fullmatch(text)]
            preferred = [text for text in labels if defaults.fullmatch(text)]
            return preferred[0] if len(preferred) == 1 else labels[0] if len(labels) == 1 else False if labels else None
        label = self.wait(choice, kind="key")
        if label is False:
            self.notify("progress", "Choose the API key project in the open Platform form. Automatic setup resumes after selection.")
            self.wait(lambda: True if self.native_selected_label(selector)
                      and not placeholder.fullmatch(self.native_selected_label(selector)) else None,
                      kind="key", timeout=600)
        else:
            self.guard("key")
            selector.select_option(label=label, timeout=5000)
            self.wait(lambda: True if self.native_selected_label(selector) == label else None, kind="key")
        return True

    def select_native_expiry(self, dialog: Any) -> bool:
        never = re.compile(r"^(?:Never|Nunca|No expiration|Sem expiração)$", re.I)
        placeholder = re.compile(r"^(?:Select (?:an? )?(?:expiration|expiry)(?: date)?|Selecione uma validade|Expiração|Expiration)[\s.…]*$", re.I)
        selectors = dialog.locator("select:visible")
        candidates = [selectors.nth(i) for i in range(selectors.count())
                      if any(never.fullmatch(text) or placeholder.fullmatch(text)
                             for text in self.native_option_labels(selectors.nth(i)))
                      and not any(re.fullmatch(r"(?:Select project|Selecionar projeto)[\s.…]*", text, re.I)
                                  for text in self.native_option_labels(selectors.nth(i)))]
        if not candidates:
            return False
        if len(candidates) != 1:
            raise ValueError("expiry_selection_required")
        selector = candidates[0]
        def choice():
            if not selector.is_enabled():
                return None
            labels = [text for text in self.native_option_labels(selector, enabled_only=True) if never.fullmatch(text)]
            return labels[0] if len(labels) == 1 else None
        label = self.wait(choice, kind="key")
        self.guard("key")
        selector.select_option(label=label, timeout=5000)
        self.wait(lambda: True if self.native_selected_label(selector) == label else None, kind="key")
        return True

    @staticmethod
    def expiry_control_value(text: str) -> str:
        """Some Platform triggers include both their field label and value."""
        text = " ".join(text.split())
        return re.sub(r"^(?:Expiration|Expiry|Expiração|Validade)\s*:?\s+", "", text, flags=re.I)

    def custom_key_control(self, dialog: Any, field: str) -> Any:
        """Resolve visible custom selectors by their displayed text or label."""
        if field == "project":
            displayed = re.compile(r"^(?:Select project|Selecionar projeto)[\s.…]*$", re.I)
            labelled = re.compile(r"^(?:Project|Projeto|Select project|Selecionar projeto)[\s:*.…]*$", re.I)
        else:
            displayed = re.compile(r"^(?:Expiration|Expiração|Select (?:an? )?(?:expiration|expiry)(?: date)?|Selecione uma validade|Never|Nunca|No expiration|Sem expiração)[\s.…]*$", re.I)
            labelled = re.compile(r"^(?:Expiration|Expiry|Expiração|Validade)[\s:*.…]*$", re.I)
        matches = []
        for role in ("combobox", "button"):
            controls = dialog.get_by_role(role)
            text_matches = [controls.nth(i) for i in range(controls.count())
                            if controls.nth(i).is_visible()
                            and displayed.fullmatch(self.expiry_control_value(controls.nth(i).inner_text())
                                if field == "expiry" else controls.nth(i).inner_text().strip())]
            if text_matches:
                matches.extend(text_matches)
            else:
                controls = dialog.get_by_role(role, name=labelled)
                matches.extend(controls.nth(i) for i in range(controls.count()) if controls.nth(i).is_visible())
        if len(matches) > 1:
            raise ValueError(field + "_selection_required")
        return matches[0] if len(matches) == 1 and matches[0].is_enabled() else None

    def select_custom_project(self, dialog: Any) -> None:
        try:
            control = self.wait(lambda: self.custom_key_control(dialog, "project"), kind="key")
            self.guard("key")
            self.click_custom_selector(control)
            def project_option():
                default = self.page.get_by_role("option", name=re.compile(r"^(?:Default project|Projeto padrão)$", re.I))
                if default.count() == 1 and default.is_visible():
                    return default
                options = self.page.get_by_role("option").filter(visible=True)
                return options if options.count() == 1 else None
            project = self.wait(project_option, kind="key")
            selected_label = project.inner_text().strip()
            self.guard("key")
            self.click_custom_selector(project)
            self.wait(lambda: True if control.inner_text().strip() == selected_label else None, kind="key")
        except ValueError as exc:
            if str(exc) == "platform_ui_needs_attention":
                raise ValueError("project_selection_required") from None
            raise

    def select_custom_expiry(self, dialog: Any) -> None:
        never = re.compile(r"^(?:Never|Nunca|No expiration|Sem expiração)$", re.I)
        try:
            control = self.wait(lambda: self.custom_key_control(dialog, "expiry"), kind="key")
            self.guard("key")
            self.click_custom_selector(control)
            def never_option():
                options = self.page.get_by_role("option", name=never)
                return options if options.count() == 1 and options.is_visible() else None
            option = self.wait(never_option, kind="key")
            self.guard("key")
            self.click_custom_selector(option)
            self.wait(lambda: True if never.fullmatch(self.expiry_control_value(control.inner_text())) else None, kind="key")
        except ValueError as exc:
            if str(exc) == "platform_ui_needs_attention":
                raise ValueError("expiry_selection_required") from None
            raise

    @staticmethod
    def click_custom_selector(control: Any) -> None:
        # Playwright's normal click already generates the pointer sequence.
        # The extension needs the corresponding fixed, packaged DOM action.
        action = getattr(control, "pointer_click", None) or control.click
        action(timeout=5000)

    def select_existing_tunnel(self) -> str:
        """Open an observed resource, then verify its ID; never create on retry."""
        from .openai_browser_enrollment import _TUNNEL_DOM, TUNNEL_PATTERN
        identifier = self.existing_tunnel_id
        name = self.existing_tunnel_name
        if not TUNNEL_PATTERN.fullmatch(identifier) or (name and not re.fullmatch(r"SENTRA-[0-9a-f]{10}", name)):
            raise ValueError("saved_tunnel_not_visible")
        def locate():
            if identifier in set(self.page.evaluate(_TUNNEL_DOM)):
                return True
            # IDs may occur only in detail views. Select an actual observed
            # link, or the exact protected name, without constructing a URL.
            links = self.page.locator('a[href*=' + json.dumps(identifier) + ']:visible')
            if links.count() == 1:
                return links
            if name:
                exact = re.compile('^' + re.escape(name) + '$')
                links = self.page.get_by_role('link', name=exact)
                if links.count() == 1 and links.is_visible():
                    return links
                labels = self.page.get_by_text(exact)
                if labels.count() == 1 and labels.is_visible():
                    return labels
            return None
        try:
            selected = self.wait(locate, kind="tunnel")
            if selected is not True:
                self.guard("tunnel")
                selected.click(timeout=5000)
                self.wait(lambda: True if set(self.page.evaluate(_TUNNEL_DOM)) == {identifier}
                          else None, kind="tunnel")
        except ValueError as exc:
            if str(exc) == "platform_ui_needs_attention":
                raise ValueError("saved_tunnel_not_visible") from None
            raise
        return identifier

    def run(self) -> tuple[str, str]:
        from .onboarding import OPENAI_API_KEYS_URL
        from .openai_browser_enrollment import _TUNNEL_DOM, capture_new_key_in_page, _trusted_platform_location
        self.notify("opened", "Sign in to OpenAI Platform. Authorized automatic setup resumes after login.")
        deadline = time.monotonic() + 600
        while not _trusted_platform_location(self.page.url, kind="tunnel"):
            if self.cancelled.is_set() or self.page.is_closed():
                raise RuntimeError("enrollment_cancelled")
            if time.monotonic() >= deadline:
                raise ValueError("login_required")
            self.page.wait_for_timeout(250)
        if self.existing_tunnel_id:
            tunnel = self.select_existing_tunnel()
        else:
            self.notify("progress", "Creating the SENTRA tunnel…")
            self.click(self.page, r"^(?:\+\s*)?(?:create|new|add|criar|novo|adicionar) tunnel$", "tunnel")
            dialog = self.dialog("tunnel")
            self.name_dialog(dialog, "tunnel")
            description = dialog.locator('textarea[required]:visible')
            if description.count() == 1:
                self.guard("tunnel")
                description.fill("SENTRA local MCP connection for this computer.", timeout=5000)
            self.associate_workspace(dialog)
            # Snapshot identifiers before Create; only a newly appearing ID may be used.
            before = set(self.page.evaluate(_TUNNEL_DOM))
            self.click(dialog, r"^(?:create(?: tunnel)?|criar(?: tunnel)?|save|salvar)$", "tunnel")
            def new_tunnel():
                from .openai_browser_enrollment import _single_identifier, TUNNEL_PATTERN
                values = list(set(self.page.evaluate(_TUNNEL_DOM)) - before)
                return _single_identifier(values, TUNNEL_PATTERN, label="tunnel") if values else None
            tunnel = self.wait(new_tunnel, kind="tunnel")
        if self.on_tunnel_selected is not None:
            self.on_tunnel_selected(tunnel)
        self.notify("tunnel", tunnel)
        self.guard("tunnel")
        self.notify("progress", "Opening the API key form…")
        self.page.goto(OPENAI_API_KEYS_URL, wait_until="domcontentloaded", timeout=30000)
        self.click(self.page, r"^(?:\+\s*)?(?:create new secret key|create secret key|create api key|criar nova chave secreta)$", "key")
        dialog = self.dialog("key")
        self.name_dialog(dialog, "key")
        def all_radio():
            value = dialog.get_by_role("radio", name=re.compile(r"^(?:All|Todas|Todos)$", re.I))
            return value if value.count() == 1 and value.is_visible() else None
        try:
            self.wait(all_radio, kind="key")
        except ValueError as exc:
            if str(exc) == "platform_ui_needs_attention":
                raise ValueError("all_permissions_unavailable") from None
            raise
        # Organization keys still require a project. Prefer the account's
        # Default project; never silently pick one of several custom projects.
        self.notify("progress", "Selecting the API key project…")
        native_project = self.select_native_project(dialog)
        if not native_project:
            self.select_custom_project(dialog)
        self.guard("key")
        self.wait(all_radio, kind="key")
        self.notify("progress", "Selecting API key expiration…")
        native_expiry = self.select_native_expiry(dialog)
        if not native_expiry:
            self.select_custom_expiry(dialog)
        # Project/expiry changes can rerender or reset permissions. Confirm All
        # immediately before the final Create action.
        radio = self.wait(all_radio, kind="key")
        self.guard("key")
        radio.click(timeout=5000)
        aria_checked = radio.get_attribute("aria-checked")
        checked = aria_checked == "true" if aria_checked is not None else radio.is_checked()
        if not checked:
            raise ValueError("all_permissions_unavailable")
        self.notify("progress", "Creating a new API key with All permissions…")
        self.click(dialog, r"^(?:create secret key|create new secret key|create|criar chave secreta|criar)$", "key")
        def revealed():
            try:
                return capture_new_key_in_page(self.page)
            except ValueError as exc:
                if str(exc) == "new_key_not_found":
                    return None
                raise
        return tunnel, self.wait(revealed, kind="key")
