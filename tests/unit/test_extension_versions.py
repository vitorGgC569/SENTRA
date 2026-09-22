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
    assert "OMA_CONTROLLER_IDLE_CLOSE_MS" in worker
    assert 'relayHealth = await omaRelay("/health")' in worker
    assert "const hasWork = queued > 0 || leased > 0 || activeJobs.length > 0;" in worker
    assert "if (!hasWork)" in worker
    assert "await omaCloseOwnedTabs();" in worker
    assert "await omaEnsureTabs(desiredTabs);" in worker
    assert "máximo 1 tab" in options
    assert 'chrome.tabs.query({ url: ["https://chatgpt.com/*"] })' in worker
    assert "tab.active !== true" in worker
    assert "adopted: true" in worker
    assert 'chrome.tabs.create({ url: "https://chatgpt.com/", active: false })' in worker
    assert "created.size >= OMA_POOL.maxTabs" in worker
    assert "oma_created_tabs" in worker
    assert "created.has(tabId)" in worker


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


def test_heartbeat_never_creates_tabs_and_personal_tabs_are_not_adopted():
    observer = _read("observer.js")
    worker = _read("service-worker.js")

    heartbeat = worker.split("async function omaHeartbeatWorkers()", 1)[1].split(
        "async function omaFlushOutbox()", 1
    )[0]
    assert "omaEnsureTabs()" not in heartbeat
    assert 'omaSendSwPing("OMA_IDLE_WAKE")' in observer
    assert "await omaOwnedTabIds()" in worker
    assert "if (!owned.has(tabId))" in worker
