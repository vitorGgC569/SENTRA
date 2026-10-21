"""Initialize and exercise the Tcl/Tk runtime shipped inside frozen GUIs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _native_path(path: Path) -> str:
    value = str(path.resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return value


def prepare_gui_runtime() -> None:
    """Use bundled resources, including paths under redirected Windows folders."""
    if not getattr(sys, "frozen", False):
        return
    root = Path(sys._MEIPASS)
    tcl, tk = root / "_tcl_data", root / "_tk_data"
    if not (tcl / "init.tcl").is_file() or not (tk / "tk.tcl").is_file():
        raise RuntimeError("bundled_tcl_tk_resources_missing")
    os.environ["TCL_LIBRARY"] = _native_path(tcl)
    os.environ["TK_LIBRARY"] = _native_path(tk)


def check_gui_runtime(report: Path | None = None) -> dict:
    result = {"schema": 1, "ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "tk_window_created": False, "ttk_widgets_created": False,
              "window_destroyed": False, "starts_product_services": False,
              "accesses_browser_or_account": False}
    root = None
    try:
        prepare_gui_runtime()
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        root.withdraw()
        result["tk_window_created"] = True
        frame = ttk.Frame(root)
        ttk.Label(frame, text="SENTRA GUI runtime check").pack()
        ttk.Button(frame, text="Check").pack()
        frame.pack()
        root.update_idletasks()
        result.update(ttk_widgets_created=True,
                      tcl_version=str(root.tk.eval("info patchlevel")),
                      tk_version=str(root.tk.eval("package require Tk")))
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    finally:
        if root is not None:
            try:
                root.destroy()
                result["window_destroyed"] = True
            except Exception:
                pass
    result["ok"] = all(result[key] for key in
                       ("tk_window_created", "ttk_widgets_created", "window_destroyed"))
    if report is not None:
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if check_gui_runtime(args.report)["ok"] else 2)
