#!/usr/bin/env python3
"""Build the .oxt: zip everything under src/ into dist/superdocs-writer-sidebar.oxt."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
DIST = ROOT / "dist"


def main():
    DIST.mkdir(exist_ok=True)
    oxt = DIST / "superdocs-writer-sidebar.oxt"
    with zipfile.ZipFile(oxt, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(SRC.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(SRC).as_posix())
    print(f"built {oxt} ({oxt.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
