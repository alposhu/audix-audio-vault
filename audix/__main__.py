"""Entry point: `python -m audix` or the `audix` console script."""
from __future__ import annotations

import sys


def main() -> int:
    from audix.app import run
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
