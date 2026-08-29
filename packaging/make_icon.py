#!/usr/bin/env python3
"""Generate packaging/audix.ico for the executable.

Draws the shared mark from audix.ui.branding, so the taskbar icon, the window
icon, and the repository logo are all literally the same drawing.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841 - needed for QPixmap

    from audix.ui.branding import draw_mark

    target = HERE / "audix.ico"
    # Qt writes a single-image ICO; 256px is the size Windows scales from best.
    if not draw_mark(256).save(str(target), "ICO"):
        print("Could not write ICO (Qt ICO plugin unavailable).", file=sys.stderr)
        return 1
    print(f"Wrote {target.name}  ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
