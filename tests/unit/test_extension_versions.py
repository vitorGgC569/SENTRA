"""Extension hardening contracts: version lockstep, lazy controller and recovery."""
import json
import re
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent.parent / "edge_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_in_lockstep():
    manifest = json.loads(_read("manifest.json"))
    sw = re.search(r'OMA_SW_VERSION = "([^"]+)"', _read("service-worker.js")).group(1)
    cs = re.search(r'OMA_CS_VERSION = "([^"]+)"', _read("content-script.js")).group(1)
    assert manifest["version"] == sw == cs, (manifest["version"], sw, cs)


def test_node_syntax_if_available():
    import shutil
    import subprocess

    if not shutil.which("node"):
        return
    for name in ("service-worker.js", "content-script.js", "selectors.js", "observer.js"):
        result = subprocess.run(
            ["node", "--check", str(EXT / name)],
            capture_output=True,
        )
        assert result.returncode == 0, f"{name}: {result.stderr.decode()[:300]}"


def test_additional_checks_recovery_contract_present():
    content = _read("content-script.js")
    observer = _read("observer.js")

    assert "omaIsAdditionalChecksMessage" in content
    assert "omaFindAdditionalChecksBannerText(false)" in content
    assert "omaMaybeRecoverGlobalAdditionalChecks" in content
    assert "MutationObserver(omaScheduleGlobalAdditionalChecksScan)" in content
    assert "omaStopGenerationForRecovery" in content
    assert 'omaSendMessage("Continue", [])' in content
    assert "OMA_MAX_ADDITIONAL_CHECK_RECOVERIES = 2" in content
    assert "omaAdditionalChecksRecoveryPromise" in content
    assert "ADDITIONAL_CHECKS_LOOP" in content
    assert "omaFindAdditionalChecksBannerText" in observer
    assert "omaRecoverAdditionalChecks()" in observer


def test_recovery_scans_transient_dom_without_treating_chat_text_as_system_banner():
    content = _read("content-script.js")
    finder = content.split(
        "function omaFindAdditionalChecksBannerText", 1
    )[1].split("async function omaStopGenerationForRecovery", 1)[0]
    assert "document.createTreeWalker" in finder
    assert "NodeFilter.SHOW_TEXT" in finder
    assert "scanned < 1200" in finder
    assert 'node.closest("[data-message-author-role=\'user\']")' in finder
    assert 'node.closest("[data-message-author-role=\'assistant\']")' in finder
    assert "includeAssistantFallback" in finder


def test_lazy_single_controller_contract():
    worker = _read("service-worker.js")
    options = _read("options.html")

    assert "const OMA_POOL = { minTabs: 1, maxTabs: 1 };" in worker
    assert 'relayHealth = await omaRelay("/health")' in worker
    assert "const hasWork = queued > 0 || leased > 0 || activeJobs.length > 0;" in worker
    assert "if (!hasWork)" in worker
    assert "await omaReleaseControllerReferences();" in worker
    assert "const OMA_CONTROLLER_IDLE_RELEASE_MS = 300000;" in worker
    assert "Date.now() - omaControllerLastWorkAt >= OMA_CONTROLLER_IDLE_RELEASE_MS" in worker
    browser_actions = worker.split('if (job.kind === "BROWSER_ACTION")', 1)[1].split(
        'if (job.kind === "STATUS_PROBE")', 1
    )[0]
    assert "releaseAfter = true;" in browser_actions
    assert "await omaReleaseControllerReferences();" in browser_actions
    assert "await omaEnsureTabs(desiredTabs);" in worker
    assert "máximo 1 tab" in options
    assert 'chrome.tabs.query({ url: ["https://chatgpt.com/*"] })' in worker
    assert "tab.active !== true" in worker
    assert "adopted: true" in worker
    assert "chrome.tabs.create(" not in worker
    assert "chrome.tabs.remove(" not in worker
    assert "chrome.windows.create(" not in worker
    assert "omaCreatedTabIds" not in worker
    assert "omaRememberCreated" not in worker
    assert "omaForgetCreated" not in worker
    assert "omaRememberControllerOrigin" in worker
    assert "omaRestoreControllerTab" in worker
    assert "omaRestoreControllerTabs" in worker
    assert "oma_controller_origins" in worker
    assert 'omaRelay("/workers/release"' in worker
    assert "omaReleaseRelayWorker" in worker
    assert "for (const tabId of referenced) await omaReleaseRelayWorker(tabId);" in worker
    assert "Never close" in worker or "never close" in worker


def test_live_launcher_does_not_open_edge_unless_isolated_test_is_explicit():
    launcher = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "launch_edge_workers_live.py"
    ).read_text(encoding="utf-8")
    assert "--isolated-test" in launcher
    assert 'if not args.isolated_test:' in launcher
    assert '"mode": "existing-edge"' in launcher
    assert '"browser_launched": False' in launcher
    assert 'oma_pool_size: 1' in launcher
    assert 'SENTRA_ALLOW_ISOLATED_EDGE_TEST' in launcher
    assert 'isolated-test-blocked' in launcher


def test_update_check_runs_before_pairing_gate():
    worker = _read("service-worker.js")
    tick = worker.split("async function omaTick()", 1)[1]
    assert tick.index("await omaCheckForUpdates();") < tick.index(
        "if (!settings.oma_enabled || !settings.oma_relay_token) return;"
    )


def test_conversation_id_research_protocol_present():
    worker = _read("service-worker.js")
    assert 'job.kind === "CHAT_START"' in worker
    assert 'job.kind === "CHAT_COLLECT"' in worker
    assert "omaWaitConversationIdentity" in worker
    assert "omaOpenConversationByUrl" in worker
    assert "mode=chat-start" in worker
    assert "mode=chat-collect" in worker
    probe = worker.split('if (job.kind === "STATUS_PROBE")', 1)[1].split(
        'if (job.kind === "DELETE_CHAT")', 1
    )[0]
    assert "await omaEnsureFreshScript(tabId);" in probe


def test_bfcache_read_only_recovery_is_bounded_and_never_replays_send():
    worker = _read("service-worker.js")

    helper = worker.split(
        "async function omaSendReadOnlyToTab", 1
    )[1].split("async function omaWaitTabComplete", 1)[0]
    open_conv = worker.split(
        "async function omaOpenConversationByUrl", 1
    )[1].split("async function omaWaitConversationIdentity", 1)[0]
    chat_start = worker.split('if (job.kind === "CHAT_START")', 1)[1].split(
        'if (job.kind === "CHAT_COLLECT")', 1
    )[0]
    freshness = worker.split(
        "async function omaEnsureFreshScript", 1
    )[1].split("async function omaWaitTabReady", 1)[0]

    assert "omaIsRecoverableMessageChannelError" in worker
    assert "back\\/forward cache" in worker
    assert "maxAttempts = 2" in helper
    assert "attempts = Math.max(1, Math.min" in helper
    assert "omaEnsureFreshScript(tabId)" in helper
    assert "await chrome.tabs.reload(tabId);" in helper
    assert "message channel is closed" in helper
    assert "csv === manifestVersion" in freshness
    assert 'operation: "GET_CONVERSATION_URL"' in open_conv
    assert "omaSendReadOnlyToTab(" in open_conv
    assert "4," in open_conv
    assert 'operation: "WAIT_RESPONSE"' in worker
    assert 'operation: "SEND_MESSAGE"' in chat_start
    assert "omaSendReadOnlyToTab" not in chat_start


def test_idle_wake_never_creates_tabs_and_only_scheduler_can_adopt():
    observer = _read("observer.js")
    worker = _read("service-worker.js")

    heartbeat = worker.split("async function omaHeartbeatWorkers()", 1)[1].split(
        "async function omaFlushOutbox()", 1
    )[0]
    idle_wake = worker.split('if (request.operation === "OMA_IDLE_WAKE")', 1)[1].split(
        'if (request.operation === "OMA_LEASE_PING"', 1
    )[0]

    assert "omaEnsureTabs()" not in heartbeat
    assert 'omaSendSwPing("OMA_IDLE_WAKE")' in observer
    assert "await omaOwnedTabIds()" in idle_wake
    assert "await omaTick();" in idle_wake
    assert "omaRememberOwned" not in idle_wake
    assert "chrome.tabs.create(" not in idle_wake
    assert "void omaTick();" in worker


def test_edge_screenshot_permission_is_runtime_scoped_to_chatgpt():
    manifest = json.loads(_read("manifest.json"))
    worker = _read("service-worker.js")

    # captureVisibleTab requires <all_urls> or a user-granted activeTab token.
    # SENTRA is unattended, so the manifest carries <all_urls>, while the
    # service worker narrows screenshot execution back to chatgpt.com.
    assert "<all_urls>" in manifest["host_permissions"]
    assert 'if (!/^https:\\/\\/chatgpt\\.com\\//.test(String(tabInfo.url || "")))' in worker
    assert "BROWSER_ACTION screenshot is restricted to https://chatgpt.com" in worker
    assert "chrome.tabs.captureVisibleTab" in worker


def test_auto_update_compares_full_extension_identity():
    worker = _read("service-worker.js")
    assert "data.version !== OMA_SW_VERSION" in worker
    assert "data.build_id !== OMA_BUILD_ID" in worker
    assert "data.source_hash !== OMA_SOURCE_HASH" in worker
    assert "chrome.runtime.reload();" in worker
