"""Windows tray supervisor for SENTRA Commander."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from sentra_version import SERVER_VERSION

from .diagnostics import collect
from .updater import apply_prepared_update, fetch_manifest, is_newer_version, prepare_update


class AgentSupervisor:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.process: subprocess.Popen[str] | None = None
        self.stop_requested = False
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            sibling = Path(sys.executable).with_name("sentra-agent.exe")
            return [str(sibling), "--config", str(self.config_path), "run"]
        return [sys.executable, "-B", "-m", "sentra_remote", "--config", str(self.config_path), "run"]

    def _loop(self) -> None:
        backoff = 1.0
        while not self.stop_requested:
            if not self.config_path.is_file():
                time.sleep(2)
                continue
            try:
                with self.lock:
                    self.process = subprocess.Popen(
                        self._command(),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    proc = self.process
                code = proc.wait()
                with self.lock:
                    self.process = None
                if self.stop_requested:
                    break
                time.sleep(backoff)
                backoff = min(30.0, backoff * 2)
            except Exception:
                time.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    def stop_agent(self) -> None:
        with self.lock:
            proc = self.process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    def restart(self) -> None:
        self.stop_agent()

    def shutdown(self) -> None:
        self.stop_requested = True
        self.stop_agent()
        self.thread.join(timeout=10)

    def status(self) -> str:
        with self.lock:
            proc = self.process
        if not self.config_path.is_file():
            return "Not paired"
        return "Online agent process" if proc and proc.poll() is None else "Reconnecting"


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="sentra-tray")
    parser.add_argument("--config", default=str(Path.home() / ".sentra" / "agent.json"))
    parser.add_argument("--manifest-url", default=os.environ.get("SENTRA_UPDATE_MANIFEST_URL", ""))
    parser.add_argument(
        "--auto-update",
        action="store_true",
        default=os.environ.get("SENTRA_AUTO_UPDATE", "").strip().lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--allow-unsigned-updates",
        action="store_true",
        default=os.environ.get("SENTRA_ALLOW_UNSIGNED_UPDATES", "").strip().lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument("--update-check-hours", type=float, default=float(os.environ.get("SENTRA_UPDATE_CHECK_HOURS", "6")))
    args = parser.parse_args(argv)
    if args.update_check_hours <= 0:
        parser.error("--update-check-hours must be greater than zero")
    config_path = Path(args.config).expanduser()
    supervisor = AgentSupervisor(config_path)
    auto_stop = threading.Event()

    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            supervisor.shutdown()
            return 0

    image = Image.new("RGBA", (64, 64), (25, 25, 25, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 52, 52), outline=(255, 255, 255, 255), width=4)
    draw.text((22, 18), "S", fill=(255, 255, 255, 255))

    icon: pystray.Icon

    def status_text(_item):
        return "Status: " + supervisor.status()

    def restart(_icon, _item):
        supervisor.restart()

    def diagnostics(_icon, _item):
        output = config_path.with_name("diagnostics.json")
        output.write_text(json.dumps(collect(config_path), indent=2), encoding="utf-8")
        os.startfile(output)  # type: ignore[attr-defined]

    def check_update(_icon, _item):
        if not args.manifest_url:
            return
        manifest = fetch_manifest(args.manifest_url)
        payload = {
            "current_version": SERVER_VERSION,
            "available_version": manifest["version"],
            "update_available": is_newer_version(str(manifest["version"]), SERVER_VERSION),
            "signed": bool(manifest.get("signer_thumbprint")),
        }
        output = config_path.with_name("update-ready.json")
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.startfile(output)  # type: ignore[attr-defined]

    def install_update(icon_obj, _item):
        if not args.manifest_url or not getattr(sys, "frozen", False):
            return
        manifest = fetch_manifest(args.manifest_url)
        if not is_newer_version(str(manifest["version"]), SERVER_VERSION):
            return
        prepared = prepare_update(
            args.manifest_url,
            require_signature=not args.allow_unsigned_updates,
        )
        install_dir = Path(sys.executable).resolve().parent
        supervisor.shutdown()
        apply_prepared_update(
            prepared,
            install_dir,
            manifest_url=args.manifest_url,
            auto_update=args.auto_update,
            allow_unsigned_updates=args.allow_unsigned_updates,
        )
        icon_obj.stop()

    def quit_app(icon_obj, _item):
        auto_stop.set()
        supervisor.shutdown()
        icon_obj.stop()

    def auto_update_loop() -> None:
        if not args.manifest_url or not args.auto_update or not getattr(sys, "frozen", False):
            return
        if auto_stop.wait(10.0):
            return
        interval = max(300.0, args.update_check_hours * 3600.0)
        while not auto_stop.is_set():
            try:
                manifest = fetch_manifest(args.manifest_url)
                if is_newer_version(str(manifest["version"]), SERVER_VERSION):
                    prepared = prepare_update(
                        args.manifest_url,
                        require_signature=not args.allow_unsigned_updates,
                    )
                    install_dir = Path(sys.executable).resolve().parent
                    supervisor.shutdown()
                    apply_prepared_update(
                        prepared,
                        install_dir,
                        manifest_url=args.manifest_url,
                        auto_update=True,
                        allow_unsigned_updates=args.allow_unsigned_updates,
                    )
                    icon.stop()
                    return
            except Exception:
                pass
            if auto_stop.wait(interval):
                return

    menu = pystray.Menu(
        pystray.MenuItem(status_text, lambda *_: None, enabled=False),
        pystray.MenuItem("Restart Agent", restart),
        pystray.MenuItem("Diagnostics", diagnostics),
        pystray.MenuItem("Check Update", check_update, enabled=bool(args.manifest_url)),
        pystray.MenuItem("Install Update", install_update, enabled=bool(args.manifest_url) and bool(getattr(sys, "frozen", False))),
        pystray.MenuItem("Exit", quit_app),
    )
    icon = pystray.Icon("SENTRA Commander", image, "SENTRA Commander", menu)
    if args.auto_update and args.manifest_url and getattr(sys, "frozen", False):
        threading.Thread(target=auto_update_loop, name="sentra-auto-update", daemon=True).start()
    try:
        icon.run()
    finally:
        auto_stop.set()
        supervisor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
