"""Keep the official logo and the Dot desktop icon available in packaged builds."""
from __future__ import annotations

import hashlib
from pathlib import Path
from PIL import Image
from scripts.commander import build_windows
from scripts.commander.build_brand_icon import SOURCE, ICON, FAVICON, SIZES
from sentra_canvas.native_brand import icon_path


def test_official_source_unchanged_and_ico_contains_multiple_sizes():
    assert SOURCE.exists() and ICON.exists() and FAVICON.exists()
    with Image.open(SOURCE) as source, Image.open(ICON) as icon, Image.open(FAVICON) as favicon:
        assert source.size == (1254, 1254)
        assert icon.format == "ICO"
        assert set(icon.ico.sizes()) == {(size, size) for size in SIZES}
        assert favicon.size == (256, 256)
        assert source.getpixel((0, 0)) == (0, 0, 0)
    # White monogram and both white dots must remain high-contrast.
    with Image.open(SOURCE) as source:
        assert all(max(source.getpixel(point)) >= 240 for point in
                   ((420, 830), (900, 380), (600, 600)))


def test_pyinstaller_embeds_official_icon_and_bundles_runtime_image(monkeypatch,tmp_path):
    seen=[]
    monkeypatch.setattr(build_windows,"_run",lambda args,**kwargs:seen.append(args))
    from scripts.commander import runtime_dependencies
    monkeypatch.setattr(runtime_dependencies, "require_wasmtime_pin", lambda: None)
    build_windows._build("sentra-canvas","canvas_entry.py",
                         tmp_path/"dist",tmp_path/"work",tmp_path/"spec",
                         windowed=True,extra=["--collect-all","webview"])
    command=seen[0]
    assert "--icon" in command
    assert command[command.index("--icon")+1] == str(icon_path())
    assert "--add-data" in command
    assert any("sentra_canvas/assets" in str(value) for value in command)
    assert "--noconsole" in command
    for name in ("sentra-desktop", "sentra-human"):
        build_windows._build(name,name+"_entry.py",
                             tmp_path/"dist",tmp_path/"work",tmp_path/"spec",
                             windowed=True)
        assert "--icon" in seen[-1]


def test_dot_desktop_icon_supports_windows_sizes_and_transparency():
    with Image.open(icon_path()) as icon:
        assert icon.format == "ICO"
        assert set(icon.ico.sizes()) == {(size, size) for size in SIZES}
        image = icon.convert("RGBA")
        assert image.getpixel((0, 0))[3] == 0
        r, g, b, alpha = image.getpixel((128, 128))
        assert b > r and alpha >= 240


def test_canvas_favicon_and_native_window_binding_are_both_present():
    root=Path(__file__).resolve().parents[2]
    html=(root/"sentra_canvas/static/desktop.html").read_text(encoding="utf-8")
    native=(root/"sentra_canvas/static/native.html").read_text(encoding="utf-8")
    server=(root/"sentra_canvas/__main__.py").read_text(encoding="utf-8")
    window=(root/"sentra_canvas/native_app.py").read_text(encoding="utf-8")
    assert 'href="/sentra-logo.png"' in html
    assert 'src="/sentra-logo.png"' in native
    assert '"/sentra-logo.png"' in server
    assert "window.events.shown += apply_native_icon" in window


def test_shortcut_uses_exe_icon_embedded_into_canvas():
    from sentra_remote.windows_integration import SCRIPT
    assert "exe='sentra-canvas.exe'" in SCRIPT
    assert "$link.IconLocation=$target+',0'" in SCRIPT



def test_local_canvas_serves_the_exact_official_favicon(tmp_path):
    import threading
    import urllib.request
    from sentra_canvas.service import Canvas
    from sentra_canvas.__main__ import CanvasServer

    canvas = Canvas(tmp_path / "project", state_dir=tmp_path / "state")
    server = CanvasServer(canvas, 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{server.server_port}/sentra-logo.png",
                         timeout=6) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("image/png")
            assert hashlib.sha256(response.read()).digest() == hashlib.sha256(
                FAVICON.read_bytes()).digest()
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        canvas.shutdown()
