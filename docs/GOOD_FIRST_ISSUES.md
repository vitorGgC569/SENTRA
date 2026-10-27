# Proposed starter issues

These are suggestions for the maintainer. This file does not open GitHub issues. Create the labels before filing them: `good first issue`, `help wanted`, `documentation`, `translation`, `tests`, `ci`, `cross-platform`, `dashboard`, `cleanup`.

Facts below were checked against the tree. Where an earlier draft was wrong, the correction is in the issue text.

---

## 1. Translate the `docs/ASTRA_*.md` documents to English

**Labels:** good first issue, documentation, translation

The README notes that some linked documents and application labels remain in Portuguese. `docs/` has **13** `ASTRA_*.md` files, not 14:

- `ASTRA_BUILD_ISOLADO.md`
- `ASTRA_CACHE_CONVERSAS.md`
- `ASTRA_CACHE_CONVERSAS_PROPOSTA.md`
- `ASTRA_CHAT_TURN_DIAGNOSTICO.md`
- `ASTRA_CHECKPOINT_20261015.md`
- `ASTRA_FRENTE_EXPERIENCIA.md`
- `ASTRA_FRENTE_FEDERATION.md`
- `ASTRA_FRENTE_STREAMING.md`
- `ASTRA_IMPLEMENTACAO_E_ACEITE.md`
- `ASTRA_RUNTIME_INSTALADO.md`
- `ASTRA_STREAM_CONTENT.md`
- `ASTRA_STREAM_CONTENT_UI.md`
- `ASTRA_WINDOWS_COMPARTILHADO.md`

Pick **one file per pull request**. Add `<NAME>.en.md` next to it. Keep technical terms (Dot, Grant, WorkItem) untranslated.

**Done when:** the English file exists, the original links to it, and the meaning is unchanged.

## 2. Add `docs/GLOSSARY.md`

**Labels:** good first issue, documentation

The root README now has a short glossary (Dot, Canvas, Spaces, Grant, WorkItem, Run, Operation, OMA, Candidate, quality gate, MASTER_QUEUE, Commander, Secure MCP Tunnel). Longer definitions are still scattered across `docs/DURABLE_EXECUTION.md`, `docs/ARCHITECTURE.md`, and `docs/OMA_Orquestrador_Multiagente.md`. Collect one-line definitions with links to the source docs and modules (`sentra_runtime/`, `orchestrator/`). Portuguese and English columns are welcome. Do not contradict `config.yaml`: the default seat cap is `oma.max_seats: 5` (master, executor, three validators).

## 3. Dedicated unit tests for `sentra_core.ConversationIdentity`

**Labels:** good first issue, tests

`sentra_core/` is the low-dependency core. There is still no `tests/unit/test_sentra_core_*.py`, but `ConversationIdentity` is already exercised by:

- `tests/unit/test_gemini_account_scoped_identity.py` (parse, `from_parts`, equality, invalid URLs)
- `tests/unit/test_closeout_invariants.py` (canonical URL round-trip and unsupported hosts)

A dedicated file should cover the remaining edges in `sentra_core/conversation.py`: `maybe_parse`, `matches`, and the Gemini `/u/N/` account slot. The type is a frozen dataclass; it has no separate serializer.

**Done when:** `python -B -m pytest tests/unit -q` passes with the new file, and the new tests do not duplicate the existing cases without adding an edge.

## 4. Run the pure-Python unit suite on Linux in CI

**Labels:** help wanted, ci, cross-platform

Every job in `.github/workflows/ci.yml` uses `runs-on: windows-latest`: `contract`, `python`, `unit-coverage`, `canvas`, `web-models`, and `ci-required`. `pytest.ini` has no `windows_only` marker. Add an `ubuntu-latest` job that runs the pure-Python unit tests, and mark Windows-only tests so they skip elsewhere. Start by listing which tests fail on Linux before changing CI. Do not weaken the existing Windows lanes.

## 5. Document `python -B main.py --demo` output step by step

**Labels:** good first issue, documentation

The offline smoke run creates `.oma/demo-<8 hex characters>/`, writes `math_utils.py`, and uses scripted models with real local tests. `docs/QUICKSTART.md` is the installed Desktop guide, so add a source-checkout section there or a sibling doc. Show the expected console output, the files under `.oma/demo-*` and `runs/`, and how to read `handoff.md`, `handoff.json`, and `candidate.patch`.

There is no `site/assets/demo.gif`. Checked-in previews are `site/assets/home.png`, `workspace.png`, and `selector.png`. A GIF is a bonus only after a real recording exists.

## 6. Dashboard: document the JSON APIs and close the test gaps

**Labels:** good first issue, dashboard, tests

`dashboard/server.py` is read-only and loopback. Implemented GET paths include:

- `/api/overview`
- `/api/conversations` (`state` filters; other query keys are ignored)
- `/api/failures`
- `/api/summary` (`run_id` or `project`)
- `/api/responses`
- `/api/relay/jobs`
- also `/api/chats`, `/api/program`, and `/api/web-models`

`tests/unit/test_dashboard.py` already covers overview, conversations (including `state=`), failures, summary, responses-without-a-database, and `/api/program`. `store.relay_jobs` is tested; the `/api/relay/jobs` HTTP route is not. Unknown query parameters are ignored, not rejected. Only `do_GET` is implemented, so other methods get the standard-library `501` rather than a custom JSON error.

Add `docs/DASHBOARD_API.md` with example responses, and extend the tests for the untested routes. Do not document a rejection behavior the server does not implement unless you add it, with tests, in the same pull request.

## 7. Add `CITATION.cff`

**Labels:** good first issue, documentation

`CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, and `.github/pull_request_template.md` are already in the tree, and the README links to the conduct and contributing docs. What is still missing is `CITATION.cff`. Use the version strings that already exist: `PRODUCT_VERSION` in `sentra_version.py` is the Desktop/installer version (`1.0.5`); do not invent a separate product version. Repository topics and the About text are maintainer settings, not files. See the pull request that added this document for the suggested topic list.

**Done when:** `CITATION.cff` validates and the README links to it.

## 8. Translate Desktop UI labels (pt-BR to en) via a string table

**Labels:** help wanted, translation

The README screenshots show the current Portuguese interface. User-facing strings are hard-coded in `sentra_canvas/desktop_ui/src/`, for example `primaryNav` in `shell-app.jsx` (`Início`, `Conversas`, `Assistentes`, `Espaços`). `sentra_canvas/assets/` is logos and icons, not the string table. `sentra_electron/` is a restricted display shell and is a later surface.

Propose a minimal table (pt-BR default, English optional) and convert one screen (Home) in the first pull request. Do not change session, permission, or terminal behavior.

## 9. Document the version split; do not force one number

**Labels:** good first issue, tests, documentation

`sentra_version.py` defines `PRODUCT_VERSION = "1.0.5"` (Desktop/installer) and `SERVER_VERSION = "3.0.0"` (MCP server). Those numbers are different on purpose.

- `server.json` `"version"` is `3.0.0`. `tests/unit/test_commander_release.py` already asserts it equals `SERVER_VERSION`.
- `site/release-status.json` does not store either version. It stores preview status, a baseline commit, and a link to `docs/RELEASE_1_0_5_ACCEPTANCE_2026-10-25.md`.
- `tests/unit/test_version_guard.py` and `tests/unit/test_version_regression.py` guard patch downgrades. They do not compare these three files.

A useful change is a short comment or test that states this split and fails if `server.json` drifts from `SERVER_VERSION` (that check already exists) or if someone copies `PRODUCT_VERSION` into `server.json`. Do not make `site/release-status.json` equal `1.0.5` or `3.0.0` unless the release process starts publishing a version field there.

## 10. Remaining root cleanup (do not repeat the moves already done)

**Labels:** help wanted, cleanup

Already moved, with output paths kept at the repository-root `runs/` directory:

- `build_audit_batch.py` and `build_fix_batch.py` → `scripts/`
- `swarm.py` and `swarm_poll.py` → `scripts/legacy/`
- `Mini companions (1).html` → `docs/design/mini-companions.html` (original Dot mascot reference; do not delete it)
- `qa_dot_import_20261012_a7c913/` → `tests/fixtures/qa_dot_import_20261012_a7c913/`

Leave these at the root. CI and tests require the paths:

- `requirements.txt`, `requirements.lock.txt` (`cache-dependency-path` and `scripts/ci/verify_release_contract.py`)
- `requirements-commander.txt`, `requirements-integrations.txt` (move only if every reference, including docs and workflows, is updated in the same change)
- `sentra-cli.cmd`, `sentra-cli.ps1` (documented launchers)
- `main.py`, `sentra_version.py`, `config.yaml`, `pytest.ini`, `server.json`

Do not bulk-move `docs/` into `docs/reports/`. Dated reports are linked from the README and from other docs. Do not move `sentra_executors/*HANDOFF*.md` or `sentra_collab/SPRINT_*.md`; package READMEs and `docs/integral/` link to those paths.

`docs/architecture/evidence/2026-10-23/structure.json` is a dated snapshot and still names the old root paths. Leave it.

The batch builders still read a machine-local project path inside the script. Treat them as historical helpers, not as a supported entry point.

## 11. Example `MASTER_QUEUE` walkthrough

**Labels:** good first issue, documentation

`docs/MASTER_QUEUE.example.json` exists and has no prose guide. The sample job sets `"agents": 6`. The queue passes that number through as `max_seats` for the job (`orchestrator/master_queue.py`). The default in `config.yaml` is `oma.max_seats: 5`, and the code accepts 1–8. A short doc should show how to split a larger project into roughly 250-line runs, how to feed them with `--supervise`, and what `agents` changes. Do not tell readers that 6 is the default seat count.

## 12. Local-model path guide (Ollama/vLLM) without Edge

**Labels:** help wanted, documentation, cross-platform

Without Edge, the README says to use `--provider local --reviewer local` with Ollama or vLLM and to configure `local_model` in `config.yaml`. The checked-in example points at `http://127.0.0.1:11434/v1` (Ollama) and names `qwen2.5:0.5b-instruct-q4_K_M`. The comment in `config.yaml` also mentions port `8000` for vLLM. Write a guide that was actually run: model choice, config snippet, and a first mission. This is the practical path for contributors who are not on Windows with Edge. `python -B main.py --doctor` checks the local model only when the selected provider is `local`; with the default `extension` routing it checks the relay instead.
