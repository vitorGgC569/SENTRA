# SENTRA Commander v1

SENTRA Commander v1 extends the local SENTRA MCP into a secure multi-device product.

## Architecture

Client (ChatGPT / Claude / Codex)
→ OAuth-protected SENTRA Cloud MCP
→ durable RemoteStore / Relay
→ outbound-only SENTRA Agent
→ local SENTRA MCP policy boundary
→ filesystem / terminal / Git / OMA / browser / sandbox.

The remote agent does not expose an inbound public port. It polls the relay over HTTPS,
maintains heartbeats, leases one job at a time, and dispatches the job through the same
local MCP tools used by direct clients.

## Remote safety invariants

- Pairing codes are one-use and expire.
- Device credentials are random bearer secrets stored only as SHA-256 hashes by the relay.
- Device credentials expire and can be rotated/revoked.
- Every device has a tool allowlist with wildcard-prefix support.
- Remote jobs have absolute deadlines and renewable leases.
- A pre-execution lease loss can be retried at most once.
- Once execution may have begun, lease loss becomes UNCERTAIN and is never automatically replayed.
- Large results use ordered chunks with per-chunk SHA-256 plus final digest validation.
- Public relay binding requires TLS.
- Public MCP binding requires OAuth resource-server configuration.
- OAuth user identity and device identity are separate credentials.
- The remote agent still enforces local allowed roots, process ownership and repository/OMA policy.

## Commander tools

Device management: sentra_pair_device, sentra_list_devices, sentra_ping,
sentra_who_am_i, sentra_set_device_tools, sentra_disconnect_device,
sentra_shutdown_remote, sentra_remote_call/result/cancel.

Parity wrappers include remote read/write, process start/output/stdin, repository
status and OMA status.

Persistent search: sentra_start_search, sentra_get_search_results,
sentra_search_wait, sentra_list_searches, sentra_stop_search.

Conversation identity: sentra_session_open creates a signed opaque application
session for stateful IDs when using stateless MCP 2026-07-28 HTTP. Process,
search, browser, sandbox, job and research IDs are isolated by that session.

Operational tools: sentra_get_config, sentra_update_config, sentra_pending_config,
sentra_usage_stats, sentra_recent_tool_calls, sentra_audit_query.

Documents: sentra_document_info, sentra_read_document (PDF/DOCX/CSV/Parquet/
JSONL/ipynb), sentra_write_pdf.

Async engineering jobs: sentra_test_start and sentra_job_start/status/wait/
result/cancel/list. Workspaces support read/write/execute grants, aliases,
session/TTL/permanent lifetime and locally approved removal.

Research: sentra_research_start/status/wait/result/cancel with single,
parallel and bounded MCTS-inspired beam-search strategies. Temporary chats are
deleted after completion/cancellation.

Browser: open/tabs/navigate/extract/screenshot/click/type/close. Browser navigation
blocks private, loopback, link-local, multicast, unspecified and reserved IP ranges.
For ChatGPT research the Edge extension runs in the user's installed Edge profile.
ChatGPT URLs never fall back to a separate Playwright/Edge profile when the principal
bridge is unavailable; they fail closed instead. The bridge keeps zero controller
references while idle. When work exists it adopts exactly one already-open, non-active
ChatGPT tab from the principal profile. If no safe existing ChatGPT tab is available,
it fails closed: it never creates or closes a browser tab, never opens another Edge/profile,
and never allocates one tab per subagent. The adopted tab's original URL is restored when
the controller is released. Branches use `CHAT_START` / `CHAT_COLLECT` with
`conversation_id`, so multiple server-side generations do not require multiple
browser tabs. The content script also performs a bounded `Stop -> Continue`
recovery when ChatGPT displays its transient “additional checks” system notice.

Engineering: create workspace/sandbox, apply candidate, verify candidate,
get evidence, rollback, close sandbox and run quality gate. Process execution
defaults to the Docker-backed `workspace` mode and fails closed when Docker is
unavailable; `unrestricted` host execution must be explicitly authorized.

## Local use today

The product can already be used locally:

    python -B -m sentra_mcp

or local HTTP:

    python -B -m sentra_mcp --transport streamable-http --host 127.0.0.1 --port 8000

Remote agent development:

    python -m sentra_remote --config ~/.sentra/agent.json pair --relay https://relay.example --code CODE --process-mode workspace
    python -m sentra_remote --config ~/.sentra/agent.json run

## Windows release

The release workflow builds:
- sentra-agent.exe
- sentra-tray.exe
- sentra-diagnostics.exe
- install.ps1 / uninstall.ps1
- release-manifest.json with SHA-256

When certificate secrets are configured, executables are Authenticode signed before packaging.
The tray supervises the agent and restarts it after crashes. The installer registers a
logon Scheduled Task and falls back to the Startup folder if task registration is unavailable.
