"""Visual evidence capture: render local HTML via headless Edge into PNG.

Stdlib only, no new dependencies. Fail-closed: every failure returns
{"ok": False, "error": ...} instead of raising, so the engine can record
the absence of evidence honestly instead of crashing the task.
Only file:// URLs of files inside the workspace are ever rendered.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

MAX_CAPTURE_BYTES = 900000  # headroom under the per-image protocol cap


def find_edge(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        # Override explícito: ausente = indisponível, nunca substitui
        # silenciosamente por outro binário.
        return explicit if Path(explicit).is_file() else None
    for candidate in EDGE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def capture_html_screenshot(html_path, out_png, width: int = 1100,
                             height: int = 750, timeout_s: int = 90,
                             edge: Optional[str] = None) -> Dict[str, Any]:
    """Render html_path headless and write a PNG to out_png. Never raises."""
    src = Path(html_path)
    if not src.is_file() or src.suffix.lower() not in {".html", ".htm"}:
        return {"ok": False, "error": f"not a renderable HTML file: {html_path}"}
    exe = find_edge(edge)
    if not exe:
        return {"ok": False, "error": "headless Edge not found; evidence unavailable"}
    try:
        width, height = max(320, min(int(width), 1920)), max(240, min(int(height), 1200))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid capture dimensions"}
    out = Path(out_png)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        # Headless Edge só escreve --screenshot em arquivo terminado em .png.
        tmp = out.parent / (out.stem + ".cap.tmp.png")
        proc = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={width},{height}",
             f"--screenshot={tmp}", src.as_uri()],
            capture_output=True, timeout=max(10, timeout_s))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "headless Edge timed out during capture"}
    except OSError as exc:
        return {"ok": False, "error": f"cannot launch Edge: {exc}"}
    if proc.returncode != 0 or not tmp.is_file():
        return {"ok": False,
                "error": f"Edge capture failed (rc={proc.returncode})"}
    try:
        raw = tmp.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"cannot read capture: {exc}"}
    if raw[:8] != PNG_MAGIC or not raw[8:] or len(raw) > MAX_CAPTURE_BYTES:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"ok": False, "error": "capture is not a valid bounded PNG"}
    try:
        tmp.replace(out)
    except OSError as exc:
        return {"ok": False, "error": f"cannot store capture: {exc}"}
    return {"ok": True, "path": str(out),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "width": width, "height": height}


def capture_task_renders(html_files: List[Any], evidence_dir,
                         timeout_s: int = 90,
                         edge: Optional[str] = None) -> List[Dict[str, Any]]:
    """Capture up to 2 HTML renders into evidence_dir. Returns successes only;
    failures are the caller's signal to record absence of evidence."""
    done = []
    for i, name in enumerate(list(html_files or [])[:2]):
        rec = capture_html_screenshot(name, Path(evidence_dir) / f"render-{i + 1}.png",
                                      timeout_s=timeout_s, edge=edge)
        if rec.get("ok"):
            done.append(rec)
    return done
