"""Package the pinned OpenDots blue mascot as the Windows desktop icon.

The PNG artwork remains unchanged. ICO packaging provides the sizes required
by Windows; preserve OpenDots' MIT permission notice beside the output.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sentra_canvas/desktop_ui/src/assets/opendots/blue.png"
ICON = ROOT / "sentra_canvas/assets/SENTRA-DOT.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build() -> Path:
    ICON.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as source:
        source.save(ICON, format="ICO", sizes=[(size, size) for size in SIZES])
    (ICON.parent / "OPENDOTS-LICENSE.txt").write_bytes(SOURCE.with_name("LICENSE").read_bytes())
    return ICON


if __name__ == "__main__":
    print(build())
