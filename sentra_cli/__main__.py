"""CLI entrypoint for SENTRA CLI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import CLIConfig, default_model
from .repl import SentraREPL


def _configure_stdio() -> None:
    """Keep CLI output UTF-8 even when Windows inherited a legacy code page."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sentra-cli",
        description=(
            "SENTRA CLI: autonomous local engineering agent with native "
            "Maestri canvas integration"
        ),
    )
    parser.add_argument(
        "-p", "--prompt",
        help="Run one instruction non-interactively and exit",
    )
    parser.add_argument("--prompt-stdin",action="store_true",
                        help="Read one UTF-8 instruction (up to 4000 characters) from stdin")
    parser.add_argument(
        "-w", "--workspace",
        help="Project workspace (default: current directory)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="Primary SENTRA model",
    )
    parser.add_argument(
        "--effort",choices=("low","medium","high","xhigh"),
        default=os.environ.get("SENTRA_CLI_REASONING_EFFORT","low").strip().lower(),
        help="Codex reasoning effort (low, medium, high, xhigh)",
    )
    parser.add_argument(
        "--fallback-model",
        default=os.environ.get("SENTRA_CLI_FALLBACK_MODEL", "gpt-4o"),
        help="Direct OpenAI fallback model when configured",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get(
            "SENTRA_GATEWAY_URL", "http://127.0.0.1:17842/v1"
        ),
        help="SENTRA Model Gateway URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Maximum provider turn duration in seconds (default: 30 minutes)",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=8,
        help="Maximum deterministic tool rounds per user turn",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Do not try to start the SENTRA Web runtime when unavailable",
    )
    sessions = parser.add_mutually_exclusive_group()
    sessions.add_argument("--session-id", help="Create or reopen a named persistent conversation")
    sessions.add_argument("--resume", help="Resume an existing conversation without automatically submitting a prompt")
    parser.add_argument("--state-dir", type=Path, help="Shared SENTRA runtime state directory")
    parser.add_argument("--shell-turn", action="store_true", help="Send one authoritative shell turn, including scoped attachment refs")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--space-id", default="")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--request-key", default="")
    parser.add_argument("--attachment-ref", action="append", default=[], help="Brisa att-* reference (repeat up to four times)")
    parser.add_argument("--shell-request-status", help="Read local acknowledgement/uncertainty without sending the turn again")
    parser.add_argument("--continue", dest="continue_previous", action="store_true",
                        help="Explicitly continue the unfinished turn in --resume, using its durable journal")
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"sentra-cli {__version__}",
    )
    args = parser.parse_args(argv)
    if args.model is None:
        args.model = default_model(args.state_dir)
    return args


def _frozen_gateway_layout(
    executable: str | None = None,
) -> tuple[Path, Path, Path]:
    """Resolve installed Gateway/Web Models paths from the frozen CLI location."""
    install_dir = Path(executable or sys.executable).resolve().parent
    checkout = install_dir / "third_party" / "codex-chatgpt-web"
    launcher = (
        install_dir
        / "web-models"
        / "win-unpacked"
        / "Codex Web GPT.exe"
    )
    return install_dir, checkout, launcher


def _run_frozen_gateway_service(argv: list[str]) -> int:
    from sentra_model_gateway.gateway import (
        GatewayConfig,
        GatewayServer,
        load_or_create_gateway_admin_token,
    )
    from sentra_remote.product import ProductPaths

    parser = argparse.ArgumentParser(
        prog=Path(sys.executable).name,
        description="SENTRA loopback Responses gateway",
    )
    parser.add_argument(
        "--upstream",
        default=os.environ.get(
            "SENTRA_WEB_UPSTREAM", "http://127.0.0.1:17841"
        ),
    )
    parser.add_argument("--port", type=int, default=17842)
    parser.add_argument("--launch-upstream", action="store_true")
    args = parser.parse_args(argv)

    install_dir, checkout, launcher = _frozen_gateway_layout()
    if args.launch_upstream and not launcher.is_file():
        raise FileNotFoundError(
            f"installed Web Models launcher is missing: {launcher}"
        )

    state_root = ProductPaths.default(install_dir).state_dir
    admin_token = (
        os.environ.get("SENTRA_GATEWAY_ADMIN_TOKEN", "").strip()
        or load_or_create_gateway_admin_token(state_root)
    )
    config = GatewayConfig(
        upstream=args.upstream,
        port=args.port,
        checkout=checkout,
        launcher_executable=launcher if launcher.is_file() else None,
        state_root=state_root,
        admin_token=admin_token,
        upstream_control_token=os.environ.get(
            "SENTRA_WEB_CONTROL_TOKEN", ""
        ),
        connector_name=os.environ.get(
            "SENTRA_CONNECTOR_NAME", "SENTRA"
        ),
    )
    server = GatewayServer(config)
    headless_client = None
    owns_headless = False
    try:
        if args.launch_upstream:
            from .client import ModelClient

            headless_client = ModelClient(
                CLIConfig(
                    workspace=install_dir,
                    auto_start_gateway=False,
                )
            )
            launch_result = headless_client._spawn_headless_upstream()
            owns_headless = launch_result.startswith("upstream pid=")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if owns_headless and headless_client is not None:
            headless_client._stop_headless_upstream()
        server.server_close()
    return 0


def _run_gateway_service(argv: list[str]) -> int:
    """Run the loopback Gateway while keeping upstream recovery headless."""
    if getattr(sys, "frozen", False):
        return _run_frozen_gateway_service(argv)

    from sentra_model_gateway.gateway import main as gateway_main
    from .client import ModelClient

    launch_headless = "--launch-upstream" in argv
    forwarded = [item for item in argv if item != "--launch-upstream"]
    headless_client = ModelClient(
        CLIConfig(
            workspace=Path.cwd().resolve(),
            auto_start_gateway=False,
        )
    )
    owns_headless = False
    if launch_headless:
        launch_result = headless_client._spawn_headless_upstream()
        owns_headless = launch_result.startswith("upstream pid=")

    previous = sys.argv[:]
    try:
        sys.argv = [sys.argv[0], *forwarded]
        gateway_main()
        return 0
    finally:
        sys.argv = previous
        if owns_headless:
            headless_client._stop_headless_upstream()


def stream_turn(
    chunk_source,
    *,
    receipts=(),
    required=("coordinator",),
    write=None,
    on_delta=None,
    on_phase=None,
    announce=True,
) -> dict:
    """Print one turn by iterating the orchestrated generator.

    Coordinating is written before any delta. Each new delta is written
    before the next chunk is pulled. Text already shown is not written
    again. ``unit_gate`` is only the named receipt check. It is not
    ``reconcile_coordinator_trio`` and it is not an exit code.
    """
    from .orchestrated_stream import orchestrate_stream

    def emit(text: str) -> None:
        if write is None:
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        write(text)

    shown = ""
    unit_gate = False
    for event in orchestrate_stream(
        chunk_source, receipts=receipts, required=required,
    ):
        kind = event.get("kind")
        if kind == "progress" and event.get("phase") == "coordinating":
            if announce:
                emit("coordinating\n")
                if on_phase is not None:
                    on_phase("coordinating")
            continue
        if kind == "delta":
            text = event.get("text")
            if not isinstance(text, str) or text == "":
                continue
            # A cumulative snapshot only adds its new tail. The same phrase
            # later in a long answer is still a new fragment and must be kept.
            if shown and text.startswith(shown):
                text = text[len(shown):]
            if not text:
                continue
            emit(text)
            shown += text
            if on_delta is not None:
                on_delta(text)
            continue
        if kind == "result":
            unit_gate = event.get("success") is True
    if shown and not shown.endswith("\n"):
        emit("\n")
    return {
        "shown": shown,
        "unit_gate": unit_gate,
        "delivery": "not_submitted",
    }


def process_exit(visible, client=None) -> int:
    """Map a finished print to a process status.

    UNCERTAIN stays 3 and is never rewritten to 0. A missing unit receipt
    is not 0. A 0 means the printer finished with that receipt and the
    delivery was not UNCERTAIN. It does not close the coordinator trio.
    """
    states: list[str] = []
    if isinstance(visible, dict):
        mark = visible.get("delivery")
        if isinstance(mark, str) and mark:
            states.append(mark)
    if client is not None:
        mark = getattr(client, "last_delivery_state", None)
        if isinstance(mark, str) and mark:
            states.append(mark)
    if "uncertain" in states:
        return 3
    if client is not None and getattr(client, "last_error", None):
        return 1
    if isinstance(visible, dict):
        return 0 if visible.get("unit_gate") is True else 1
    return 0 if visible == 0 else 1


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv[:1] == ["--gateway-service"]:
        return _run_gateway_service(effective_argv[1:])
    if effective_argv[:1] == ["--job-worker"]:
        if len(effective_argv) != 2:
            print(
                "sentra-cli: --job-worker requires one job file",
                file=sys.stderr,
            )
            return 2
        from .jobs import run_job_file

        return run_job_file(Path(effective_argv[1]))
    args = parse_args(effective_argv)
    if args.prompt_stdin:
        if args.prompt is not None or args.continue_previous:
            print("sentra-cli: --prompt-stdin cannot be combined with --prompt or --continue",file=sys.stderr)
            return 2
        try:
            source=getattr(sys.stdin,"buffer",sys.stdin)
            value=source.read(16385)
            if len(value)>16384:raise ValueError("instruction bytes exceeded limit")
            text=value.decode("utf-8") if isinstance(value,bytes) else value
            if not isinstance(text,str) or not text.strip() or len(text)>4000:
                raise ValueError("invalid instruction size")
            args.prompt=text
        except (OSError,ValueError,AttributeError):
            print("sentra-cli: stdin instruction must be valid UTF-8 and contain 1-4000 characters",file=sys.stderr)
            return 2
    workspace = (
        Path(args.workspace).expanduser().resolve()
        if args.workspace
        else Path.cwd().resolve()
    )
    if not workspace.is_dir():
        print(
            f"sentra-cli: workspace does not exist or is not a directory: "
            f"{workspace}",
            file=sys.stderr,
        )
        return 2
    if args.timeout <= 0:
        print("sentra-cli: --timeout must be > 0", file=sys.stderr)
        return 2
    if args.max_tool_rounds <= 0:
        print("sentra-cli: --max-tool-rounds must be > 0", file=sys.stderr)
        return 2
    if args.continue_previous and (not args.resume or args.prompt is not None):
        print("sentra-cli: --continue requires --resume and cannot be combined with --prompt", file=sys.stderr)
        return 2

    config = CLIConfig(
        workspace=workspace,
        model=args.model,
        reasoning_effort=args.effort,
        web_reasoning_effort=args.effort if str(args.model).startswith('sentra/chatgpt-web/') else None,
        fallback_model=args.fallback_model,
        gateway_url=args.gateway_url,
        timeout_s=args.timeout,
        max_tool_rounds=args.max_tool_rounds,
        auto_start_gateway=not args.no_auto_start,
        session_id=args.resume or args.session_id,
        resume_session=bool(args.resume),
        state_root=args.state_dir,
    )
    try:
        if args.shell_turn or args.shell_request_status:
            import json
            from .shell_bridge import ShellBridge
            bridge = ShellBridge(config)
            if args.shell_request_status:
                print(json.dumps(bridge.request_status(args.shell_request_status), ensure_ascii=False))
                return 0
            if not args.prompt or not args.space_id or not args.conversation_id or not args.request_key:
                raise ValueError("--shell-turn requires prompt, Space/conversation IDs and one stable request-key")
            result = bridge.send_turn(args.prompt, project_id=args.project_id,
                space_id=args.space_id, conversation_id=args.conversation_id,
                request_key=args.request_key, attachments=args.attachment_ref)
            print(json.dumps(result, ensure_ascii=False))
            return 3 if (result.get("value") or {}).get("status") == "uncertain" else 0
        if args.attachment_ref:
            raise ValueError("attachment refs require --shell-turn; attachments never silently fall back to text")
        repl = SentraREPL(config)
        if args.continue_previous:
            return process_exit(repl.continue_previous(), repl.agent.client)
        if args.prompt is not None:
            return process_exit(repl.run_one_shot(args.prompt), repl.agent.client)
        repl.run_interactive()
        return 0
    except KeyboardInterrupt:
        return 130
    except EOFError:
        return 0
    except (ValueError, PermissionError, FileNotFoundError, RuntimeError) as exc:
        print(f"sentra-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
