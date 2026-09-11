# AutonomousInfinityAI 🤖♾️

**AutonomousInfinityAI** is a multi-agent, multi-session coding orchestrator that pairs a fast, local LLM (**Qwen**) as the local director and critic with powerful, high-capacity web LLMs (**ChatGPT Web**) as remote specialized code generators.

---

## 🏗️ Architecture Overview

```
                          [ Prompt Inicial ]
                                  │
                                  ▼
                ┌───────────────────────────────────┐
                │        Qwen Controller            │
                │  (Local via Ollama / vLLM)        │
                └─────────────────┬─────────────────┘
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      ▼                           ▼                           ▼
┌───────────┐               ┌───────────┐               ┌───────────┐
│ Architect │               │Implementer│               │ Reviewer  │
│  (Session)│               │ (Session) │               │ (Session) │
└─────┬─────┘               └─────┬─────┘               └─────┬─────┘
      │                           │                           │
      └───────────────────────────┼───────────────────────────┘
                                  ▼
                ┌───────────────────────────────────┐
                │    Playwright Browser Engine      │
                │    (Chrome / ChatGPT Web UI)      │
                └─────────────────┬─────────────────┘
                                  │
                                  ▼
                ┌───────────────────────────────────┐
                │     Git Sandbox & Command Runner  │
                │     (Patch Apply + Validation)    │
                └───────────────────────────────────┘
```

---

## 🔑 Key Features

- **Double-Loop State Machine**: Outer project loop (`ANALYZE` ➔ `PLAN` ➔ `DISPATCH` ➔ `COLLECT` ➔ `CRITIQUE` ➔ `APPLY` ➔ `VALIDATE`) and inner session loop.
- **Zero API Rate Limit Exhaustion**: Offloads file reads, diff analysis, log parsing, and prompt structuring to Qwen running locally via Ollama or vLLM.
- **Chrome Session Bridge**: Connects directly to your open browser session (via `--cdp-url http://localhost:9222`) or authenticated Playwright contexts (`auth.json`), avoiding Cloudflare bot blocks.
- **Auto-Continuation Handling**: Detects truncated browser responses, requests exact continuations, and stitches diffs seamlessly.
- **Git Worktree Isolation**: All patch proposals are applied and tested in clean git environments before being committed.
- **Stagnation & Anti-Loop Protection**: Tracks progress hashes and limits repeated failures or non-progressing iterations.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd C:\Users\vitor\OneDrive\Desktop\AutonomousInfinityAI
pip install -r requirements.txt
playwright install chromium
```

### 2. Start Qwen Local (Ollama)
```bash
ollama run qwen2.5-coder:14b
```
*(Ollama exposes an OpenAI-compatible endpoint at `http://127.0.0.1:11434/v1`)*

### 3. (Optional) Open Chrome with Remote Debugging
If you want AutonomousInfinityAI to send messages to your already-logged-in ChatGPT account in Google Chrome:
```cmd
chrome.exe --remote-debugging-port=9222
```

### 4. Run AutonomousInfinityAI
```bash
python main.py --job-id projeto-001 --prompt "Fix all failing tests and implement persistent storage" --workspace C:\caminho\para\seu\projeto
```

---

## 📂 Project Structure

```
AutonomousInfinityAI/
├── main.py                     # CLI Entrypoint
├── config.yaml                 # System & Model Configuration
├── requirements.txt            # Python Dependencies
├── README.md                   # Documentation
├── orchestrator/               # State machine & Dispatcher
│   ├── state_machine.py        # Phase enum, JobSpec, JobState, StateStore
│   ├── dispatcher.py           # Core execution loop
│   ├── aggregator.py           # Structured output parsing & aggregation
│   ├── progress.py             # Progress hashing & stagnation tracking
│   └── stop_conditions.py     # Success & failure criteria checkers
├── browser/                    # Browser Engine
│   ├── pool.py                 # Multi-session pool with locks
│   ├── session.py              # Playwright & CDP bridge
│   ├── site_adapter.py         # ChatGPT DOM locators & adapters
│   └── response_capture.py     # Stability & completion detector
├── local_model/                # Local LLM Integration
│   ├── qwen_client.py          # OpenAI-compatible local client
│   ├── prompts.py              # System envelope prompt builders
│   └── schemas.py              # Pydantic structured output schemas
├── workspace/                  # Git & Testing Sandbox
│   ├── git_manager.py          # Worktree & diff management
│   ├── patch_manager.py        # Unified diff parser & applicator
│   ├── command_runner.py       # Subprocess build & test runner
│   └── validator.py            # Comprehensive validation suite
├── prompts/                    # System Prompts per Role
│   ├── architect.md
│   ├── implementer.md
│   ├── reviewer.md
│   └── continuation.md
└── runs/                       # Persistent Job Logs & States
```

---

## ⚙️ Configuration (`config.yaml`)

```yaml
local_model:
  base_url: "http://127.0.0.1:11434/v1"
  model_name: "qwen2.5-coder:14b"
  temperature: 0.1

browser:
  headless: false
  storage_state_path: "auth.json"
  cdp_url: "http://localhost:9222"  # Set when using open Chrome debugging

orchestrator:
  max_rounds: 20
  max_parallel_sessions: 3
  no_progress_limit: 3
  repeated_failure_limit: 3
```

---

## 📜 License
MIT License. Created for Autonomous Multi-Agent Development.
