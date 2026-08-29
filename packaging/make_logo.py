#!/usr/bin/env python3
"""Generate audix/assets/logo.png — the mark used on the repository page.

Draws the shared mark from audix.ui.branding, so the README logo, the window
icon, and the executable's .ico cannot drift apart.

    python packaging/make_logo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

SIZES = {"logo.png": 512, "logo-256.png": 256}


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841

    from audix.ui.branding import draw_mark

    assets = ROOT / "audix" / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    for name, size in SIZES.items():
        target = assets / name
        if not draw_mark(size).save(str(target), "PNG"):
            print(f"Failed to write {target}", file=sys.stderr)
            return 1
        print(f"Wrote {target.relative_to(ROOT)}  ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
