"""Installer-authorized enrollment, bounded UI automation and verified storage."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Callable

from .product import ProductPaths, configure_tunnel, tunnel_credential_storage, tunnel_key_update
from .secrets import protect_secret, unprotect_secret


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

    def __init__(self, page: Any, notify: Callable, cancelled: Any, *, existing_tunnel_id: str = "") -> None:
        self.page, self.notify, self.cancelled = page, notify, cancelled
        self.name = "SENTRA-" + uuid.uuid4().hex[:10]
        self.existing_tunnel_id = existing_tunnel_id

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
        # Wait for hydrated controls before deciding that a tunnel is absent.
        self.wait(lambda: self.button(self.page, r"^(?:\+\s*)?(?:create|new|add|criar|novo|adicionar) tunnel$"), kind="tunnel")
        visible = set(self.page.evaluate(_TUNNEL_DOM))
        if self.existing_tunnel_id and self.existing_tunnel_id in visible:
            tunnel = self.existing_tunnel_id
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
        self.notify("tunnel", tunnel)
        self.guard("tunnel")
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
        select_project = dialog.get_by_role("button", name=re.compile(r"^(?:Select project|Selecionar projeto)", re.I))
        if select_project.count() == 1:
            self.click(dialog, r"^(?:Select project|Selecionar projeto).*", "key")
            def project_option():
                default = self.page.get_by_role("option", name=re.compile(r"^(?:Default project|Projeto padrão)$", re.I))
                if default.count() == 1 and default.is_visible():
                    return default
                options = self.page.get_by_role("option").filter(visible=True)
                return options if options.count() == 1 else None
            project = self.wait(project_option, kind="key")
            self.guard("key")
            project.click(timeout=5000)
        self.guard("key")
        self.wait(all_radio, kind="key")
        expiry = dialog.get_by_role("button", name=re.compile(r"^(?:Expiration|Expiração)", re.I))
        if expiry.count() == 1:
            self.click(dialog, r"^(?:Expiration|Expiração).*", "key")
            def never_option():
                option = self.page.get_by_role("option", name=re.compile(r"^(?:Never|Nunca|No expiration)$", re.I))
                return option if option.count() == 1 and option.is_visible() else None
            option = self.wait(never_option, kind="key")
            self.guard("key")
            option.click(timeout=5000)
            self.wait(lambda: True if re.search(r"Never|Nunca|No expiration", expiry.inner_text(), re.I) else None, kind="key")
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
