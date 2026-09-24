from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _patched_files(patch_text: str) -> set[str]:
    return set(re.findall(r"^diff --git a/(.+?) b/(.+?)$", patch_text, flags=re.MULTILINE)[i][1] for i in range(len(re.findall(r"^diff --git a/(.+?) b/(.+?)$", patch_text, flags=re.MULTILINE))))


def test_upstream_patch_file_set_matches_manifest() -> None:
    manifest = json.loads((ROOT / "integrations" / "codex_chatgpt_web" / "upstream.json").read_text(encoding="utf-8"))
    patch_text = (ROOT / manifest["integration_patch"]).read_text(encoding="utf-8")
    matches = re.findall(r"^diff --git a/(.+?) b/(.+?)$", patch_text, flags=re.MULTILINE)
    actual = {right for _, right in matches}
    assert actual == set(manifest["patch_files"])
    assert "launcher/electron/main.cjs" in actual
    assert "launcher/electron/control-server.cjs" in actual
    assert "launcher/src/App.tsx" in actual


def test_upstream_patch_applies_to_pinned_clean_checkout() -> None:
    manifest = json.loads((ROOT / "integrations" / "codex_chatgpt_web" / "upstream.json").read_text(encoding="utf-8"))
    checkout = ROOT / manifest["development_checkout"]
    patch = ROOT / manifest["integration_patch"]
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head == manifest["commit"]
    assert subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == ""
    applied = subprocess.run(
        ["git", "-C", str(checkout), "apply", "--check", str(patch)],
        capture_output=True, text=True,
    )
    assert applied.returncode == 0, applied.stderr or applied.stdout


def test_electron_doctor_is_sentra_managed() -> None:
    patch_text = (ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch").read_text(encoding="utf-8")
    assert "sentraDoctor" in patch_text
    assert "/sentra/doctor" in patch_text
    assert 'process.env.SENTRA_CONNECTOR_NAME || "SENTRA tunnel"' in patch_text
    assert 'handle("launcher:doctor", () => sentraDoctor(runtimeHost, { verifyConnector: true }))' in patch_text
    assert '/sentra/doctor?verify_connector=1' in patch_text
    assert '"verify-connector"' in patch_text
    assert 'browserHost.verifyConnector(connectorName.trim())' in patch_text
    assert 'report.mode === "sentra"' in patch_text


def test_sentra_managed_web_models_have_one_mcp_owner() -> None:
    patch_text = (ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch").read_text(encoding="utf-8")

    assert 'const CURRENT_CONNECTOR_NAME = "SENTRA tunnel";' in patch_text
    assert 'export const CHATGPT_CONNECTOR_NAME = "SENTRA tunnel";' in patch_text
    assert '"Codex Native2", "Codex Native2 DEV", "Codex Native"' in patch_text
    assert "function sentraManagedHarness()" in patch_text
    assert 'if (config.mode !== "full" || sentraManagedHarness()) return;' in patch_text
    assert "no secondary Codex Web tunnel runtime was started" in patch_text
    assert "localToolsEnabled: sentraManaged || config.mode === \"full\"" in patch_text
    assert "const report = await sentraDoctor(runtimeHost);" in patch_text
    assert 'SENTRA-managed Web Models use the single SENTRA tunnel in Automatic mode' in patch_text
    assert 'step === 0 && !sentraManaged' in patch_text
    assert '? { interactionMode: "automatic", replace: false }' in patch_text
    assert 'sentraIntegrationPatchSha256: process.env.SENTRA_INTEGRATION_PATCH_SHA256 || null' in patch_text
    assert 'function chatGptConnectorMentionQuery(appName: string)' in patch_text
    assert 'return `@${token}`;' in patch_text
    assert 'const mentionQuery = chatGptConnectorMentionQuery(this.config.appName);' in patch_text
    assert '\n+const CHATGPT_CONNECTOR_MENTION_QUERY = "@codex"' not in patch_text
    assert 'Personalized|Personalizado|个性化' in patch_text
    assert 'Unpersonalized|Não personalizado|Nao personalizado|非个性化' in patch_text
    assert 'src/adapters/chatgpt-web/browser-helper-main.ts' in patch_text
    assert 'src/adapters/chatgpt-web/launcher-helper-client.ts' in patch_text
    assert 'turn.sentraCapability ? { sentraCapability: turn.sentraCapability }' in patch_text
    assert 'message.turn.sentraCapability ? { sentraCapability: message.turn.sentraCapability }' in patch_text
    assert 'Browser helper SENTRA TurnCapability is invalid' in patch_text
    assert 'const { embeddedRuntimeInvocation, runtimeInvocation } = require("./runtime-command.cjs");' in patch_text
    assert 'if (sentraManagedHarness()) {' in patch_text
    assert 'return embeddedRuntimeInvocation({' in patch_text
