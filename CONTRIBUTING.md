# Contributing to SENTRA

Thanks for helping. Contributions are welcome in **English or Portuguese** — issues, pull requests, and reviews in either language are fine. / Contribuições são bem-vindas em **português ou inglês**.

SENTRA is a **development preview** (Windows-first). Please read [SECURITY.md](SECURITY.md) and the [Code of Conduct](CODE_OF_CONDUCT.md) first. Never report vulnerabilities in public issues.

## Setup

Documented prerequisites for the source workflow: Windows 10/11, Python 3.11+, and about 4 GB free disk. Continuous integration uses Python 3.12 on `windows-latest`. Microsoft Edge is only needed for browser-backed flows. Docker Desktop is optional; the default `config.yaml` still selects a Docker test backend, which fails closed until Docker is available or you pass `--trust-workspace` / `--demo`.

```powershell
git clone https://github.com/<you>/SENTRA
cd SENTRA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -B main.py --demo
python -B main.py --doctor
```

On Linux or macOS, activate the virtualenv with `source .venv/bin/activate` instead of `.\.venv\Scripts\Activate.ps1`.

`python -B main.py --demo` is an offline smoke run. It creates `.oma/demo-<8 hex characters>/` (or uses an empty `--workspace`), writes a `math_utils.py` fixture, and runs scripted models with real local tests. It does not call live models or Edge. `--demo` is also available as `--mock`.

`python -B main.py --doctor` prints dependency and connection diagnostics and does not call models. It exits 0 only when every check passes. With the default config, a fresh checkout reports the Docker sandbox and the Edge relay as unavailable and exits 2. That is a fail-closed diagnostic, not a successful live run.

There is no Ubuntu job in `.github/workflows/ci.yml`. Pure-Python packages can be imported on other platforms, but Windows UIA, the installer, and Edge flows are Windows-specific. See [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md).

## Tests

```powershell
python -B -m pytest tests/unit -q
python -B -m pytest tests -q
$env:OMA_DOCKER_TESTS = '1'
python -B -m pytest tests/integration/test_docker_sandbox_live.py -q
$env:OMA_LIVE_EXTENSION = '1'
python -B -m pytest tests/e2e/test_extension_live.py -s
```

`python -B -m pytest tests -q` collects everything under `tests/`: `unit/`, `integration/`, `failure/`, `load/`, `e2e/`, and the test modules that sit directly in `tests/`. `tests/js/` is Node, not pytest. `projects/site-sentra/tests/` is outside `testpaths` and is not part of this command.

`pytest.ini` sets `testpaths = tests` and does not recurse into `Auxiliares`, `.oma`, `runs`, `research`, `browser_profiles`, `.git`, `.venv`, `venv`, or `node_modules`. It does not register a `windows_only` marker.

CI's Python job runs `tests/unit` (two partitions), `tests/failure`, and `tests/integration` on `windows-latest`. It does not run `tests/load` or `tests/e2e` in that matrix. A green local `tests/unit` run is the usual pre-push check; say in the pull request which suites you actually ran.

`$env:OMA_DOCKER_TESTS = '1'` opts into real-container tests (`tests/integration/test_docker_sandbox_live.py` skips otherwise). `$env:OMA_LIVE_EXTENSION = '1'` with `tests/e2e/test_extension_live.py` creates **one real ChatGPT conversation**. Without the variable, that test skips.

Add or update tests with every behavior change. Controlled failure injection does not replace real integration evidence.

## Code map

| Path | What lives there |
|---|---|
| `main.py`, `orchestrator/` | CLI entry (`--demo`, `--doctor`, `--relay`, `--promote`, `--supervise`, `--queue`) and the OMA engine: DAG, queue, state machine, agents, verification, quality gate, providers |
| `sentra_core/` | Low-dependency primitives shared across transports. Public export today: `ConversationIdentity` |
| `sentra_runtime/` | Capability contracts, executor registry, and the WorkItem/Grant authorization bridge |
| `sentra_canvas/` | Native terminal and workspace control plane, including the Desktop UI under `sentra_canvas/desktop_ui/` |
| `sentra_cli/` | Interactive terminal assistant. `sentra-cli.cmd` runs `python -B -m sentra_cli` |
| `sentra_mcp/` | MCP server (`python -B -m sentra_mcp`). Transports: `stdio` (default) and `streamable-http` |
| `sentra_model_gateway/` | Responses gateway for supervised Web model transports |
| `sentra_remote/` | Commander remote agent, installer, and relay |
| `sentra_federation/` | Peer Gateway between two installations. Importing it does not listen or grant access |
| `sentra_interop/` | Opt-in protocol adapters (ACP, A2A, and others). Importing them does not execute external work |
| `sentra_executors/` | Capability-scoped Machine Runtime executors (Windows UIA, Daytona, and others), opt-in |
| `sentra_connectors/` | Host-bound GitHub/Drive connectors. Importing them does not connect or grant access |
| `sentra_marketplace/` | Optional connectors, skills, and plugins. This package does not mint Grants |
| `sentra_code_mode/` | Fail-closed admission for bounded Code Mode execution |
| `sentra_collab/` | Opt-in collaborative canvas boundary. No core state lives here |
| `sentra_quality/` | Read-only third-party provenance and release checks |
| `sentra_electron/` | Restricted Electron display for the Canvas. It is not a second product runtime |
| `native_bridge/`, `edge_extension/` | Authenticated relay and the Edge MV3 controller |
| `repository/`, `workspace/` | Patches, snapshots, and isolation |
| `dashboard/` | Read-only loopback monitoring server (`python -B dashboard/server.py`) |
| `local_model/` | Local Ollama/vLLM client used with `--provider local` |
| `scripts/` | CI, release, and one-off helpers. `scripts/legacy/swarm.py` and `swarm_poll.py` are the old CDP ChatGPT swarm driver; they are not a product entry point and still write under `runs/` |
| `docs/`, `site/` | Documentation and the GitHub Pages site |
| `docs/design/mini-companions.html` | Original reference sheet for the animated Dot mascots |
| `tests/` | `unit/`, `integration/`, `failure/`, `load/`, `e2e/`, `js/`, plus modules directly under `tests/` |

## Root layout

Keep product entry points at the repository root: `README.md`, `LICENSE`, `SECURITY.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`, `main.py`, `sentra_version.py`, `config.yaml`, `pytest.ini`, `server.json`, `requirements.txt`, `requirements.lock.txt`, `sentra-cli.cmd`, `sentra-cli.ps1`, `CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md`.

`requirements.lock.txt` stays at the root because CI and `scripts/ci/verify_release_contract.py` require that path. Do not move it in a drive-by cleanup.

## Pull request flow

1. Open or pick an issue. Comment before you start so two people do not duplicate the work. Suggested labels are listed in [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md); a maintainer still has to create them.
2. Fork, then branch from `main`: `fix/<short-name>`, `feat/<short-name>`, or `docs/<short-name>`.
3. Keep pull requests small (the project favours deliveries of about 250 lines) and focused on one change.
4. Run `python -B -m pytest tests/unit -q`, plus any suite that covers your change, before pushing.
5. Fill in the pull request template: what changed, how it was tested, platform, and any remaining risk.
6. Do not commit secrets, tokens, browser profiles, `runs/`, `.oma/`, or generated artifacts.
7. A maintainer reviews. Address feedback with new commits.

## Style

- Python 3.11+, type hints where practical, and the standard library first in low-dependency packages (`sentra_core`).
- Fail closed: importing a package must not connect, listen, or grant access.
- New user-facing docs in English. Portuguese translations are welcome alongside.
