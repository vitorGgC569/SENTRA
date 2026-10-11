"""Generate the Windows SENTRA icon from the approved monochrome logo.

Source is a project asset, not the original user's Downloads folder.
No stylistic changes: preserve pure black and white composition.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "sentra_canvas" / "assets"
SOURCE = ASSETS / "SENTRA-LOGO.png"
ICON = ASSETS / "SENTRA.ico"
FAVICON = ROOT / "sentra_canvas" / "static" / "sentra-logo.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build() -> tuple[Path, Path]:
    if not SOURCE.is_file():
        raise FileNotFoundError("approved SENTRA-LOGO.png is missing")
    with Image.open(SOURCE) as loaded:
        if loaded.width != loaded.height or loaded.width < 256:
            raise ValueError("SENTRA icon source must be square, at least 256px")
        image = loaded.convert("RGBA")
        image.save(ICON, format="ICO", sizes=[(size, size) for size in SIZES])
        image.resize((256, 256), Image.Resampling.LANCZOS).convert("RGB").save(
            FAVICON, format="PNG", optimize=True
        )
    return ICON, FAVICON


if __name__ == "__main__":
    icon, favicon = build()
    with Image.open(icon) as result:
        print("SENTRA_ICON_CREATED", icon, "sizes", sorted(result.ico.sizes()))
    print("SENTRA_FAVICON_CREATED", favicon)
