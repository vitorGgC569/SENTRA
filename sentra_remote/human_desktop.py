"""SENTRA Human: minimal native WebView UI over real SENTRA runtime data."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sentra_version import PRODUCT_VERSION

from .human_store import HumanStore
from .product import ProductPaths, ProductSettings


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS"))
        return root / "human_ui"
    return Path(__file__).resolve().parent / "human_ui"


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class HumanAPI:
    def __init__(self, paths: ProductPaths) -> None:
        self.paths = paths
        self.settings = ProductSettings.load(paths.settings)
        self.store = HumanStore(paths, self.settings)
        self.ensure_worker()

    def _reload(self) -> None:
        self.settings = ProductSettings.load(self.paths.settings)
        self.store.settings = self.settings

    def ensure_worker(self) -> dict[str, Any]:
        worker_exe = self.paths.install_dir / "sentra-human-worker.exe"
        if worker_exe.is_file():
            command = [
                str(worker_exe),
                "--state-dir", str(self.paths.state_dir),
                "--install-dir", str(self.paths.install_dir),
            ]
        else:
            command = [
                os.environ.get("PYTHON", sys.executable),
                "-B",
                "-m", "sentra_remote.human_worker",
                "--state-dir", str(self.paths.state_dir),
                "--install-dir", str(self.paths.install_dir),
            ]
        try:
            subprocess.Popen(
                command,
                cwd=str(self.paths.install_dir if self.paths.install_dir.is_dir() else _install_dir()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_hidden_flags(),
            )
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def bootstrap(self, conversation_id: str | None = None) -> dict[str, Any]:
        self._reload()
        return self.store.snapshot(conversation_id)

    def conversation(self, conversation_id: str) -> dict[str, Any]:
        return self.store.conversation(conversation_id)

    def create_conversation(self, workspace: str, title: str = "") -> dict[str, Any]:
        self._reload()
        return self.store.create_conversation(workspace, title)

    def send_message(self, conversation_id: str | None, workspace: str, body: str) -> dict[str, Any]:
        self._reload()
        result = self.store.send_message(conversation_id, workspace, body)
        result["worker"] = self.ensure_worker()
        return result

    def archive_conversation(self, conversation_id: str) -> dict[str, Any]:
        self.store.archive_conversation(conversation_id)
        return {"ok": True}

    def run_detail(self, key: str) -> dict[str, Any]:
        self._reload()
        return self.store.run_detail(key)

    def diff(self, workspace: str) -> dict[str, Any]:
        self._reload()
        return self.store.diff(workspace)

    def read_log(self, name: str) -> dict[str, Any]:
        return self.store.read_log(name)

    def open_control_center(self) -> dict[str, Any]:
        exe = self.paths.install_dir / "sentra-desktop.exe"
        try:
            if exe.is_file():
                subprocess.Popen([str(exe)], creationflags=_hidden_flags())
            else:
                subprocess.Popen(
                    [os.environ.get("PYTHON", sys.executable), "-B", "-m", "sentra_remote.desktop"],
                    cwd=str(_install_dir()),
                    creationflags=_hidden_flags(),
                )
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def reveal_workspace(self, workspace: str) -> dict[str, Any]:
        self._reload()
        root = self.store._workspace_allowed(workspace)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", str(root)])
            else:
                subprocess.Popen(["xdg-open", str(root)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def version(self) -> dict[str, str]:
        return {"version": PRODUCT_VERSION}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import webview

    parser = argparse.ArgumentParser(prog="sentra-human")
    parser.add_argument("--state-dir")
    parser.add_argument("--install-dir")
    parser.add_argument("--hidden", action="store_true")
    args = parser.parse_args(argv)

    if args.state_dir:
        os.environ["SENTRA_STATE_DIR"] = str(Path(args.state_dir).expanduser().resolve())
    install_dir = Path(args.install_dir).resolve() if args.install_dir else _install_dir()
    paths = ProductPaths.default(install_dir)
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    assets = _asset_dir()
    index = assets / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"SENTRA Human assets missing: {index}")

    api = HumanAPI(paths)
    window = webview.create_window(
        f"SENTRA {PRODUCT_VERSION}",
        url=index.as_uri(),
        js_api=api,
        width=1440,
        height=900,
        min_size=(980, 640),
        resizable=True,
        hidden=args.hidden,
        background_color="#080b11",
        text_select=True,
        zoomable=False,
    )
    if window is None:
        return 2
    webview.start(
        gui="edgechromium",
        debug=False,
        private_mode=False,
        storage_path=str(paths.state_dir / "webview"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
