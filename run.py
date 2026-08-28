#!/usr/bin/env python3
"""audix launcher.

Designed to work however it is started: double-clicked, run from a terminal with
the wrong interpreter, or run from the project virtual environment.

Two failure modes this guards against:

* Being launched by a Python that lacks the dependencies. If a project ``.venv``
  exists, we re-execute inside it rather than dying with a traceback; otherwise we
  print instructions instead of a stack trace.
* Vanishing before the user can read an error. Any failure pauses so the console
  window stays open when the script was double-clicked.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Import names (not pip names) of the hard dependencies. `sounddevice` is
#: deliberately absent: it is optional, and the app explains its absence rather
#: than refusing to start.
REQUIRED_MODULES = ("PySide6", "yt_dlp", "mutagen", "requests", "numpy")

#: Set when we re-execute, so a broken venv cannot cause an infinite relaunch loop.
RELAUNCH_FLAG = "AUDIX_RELAUNCHED"


def venv_python() -> Path | None:
    """Path to the project venv's interpreter, if that venv exists."""
    relative = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    candidate = HERE.joinpath(".venv", *relative)
    return candidate if candidate.is_file() else None


def missing_modules() -> list[str]:
    """Which required dependencies are not importable by the current interpreter."""
    import importlib.util

    missing = []
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def pause(prompt: str = "\nPress Enter to close...") -> None:
    """Keep a double-clicked console window open. No-op when there is no console.

    Every string this module prints is deliberately pure ASCII: a legacy Windows
    console is cp1252, and a ``UnicodeEncodeError`` raised here would skip the
    pause and close the window on the exact error the user needs to read.
    """
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt, OSError, UnicodeEncodeError):
        pass


def report_missing(missing: list[str]) -> int:
    """Explain what to install, in terms the user can act on directly."""
    interpreter = sys.executable
    print("=" * 68)
    print(" audix cannot start: required packages are missing")
    print("=" * 68)
    print()
    print(f"  Interpreter : {interpreter}")
    print(f"  Version     : Python {sys.version.split()[0]}")
    print(f"  Missing     : {', '.join(missing)}")
    print()
    print("  This Python does not have audix's dependencies installed.")
    print()
    print("  Fix it by creating the project environment and using it:")
    print()
    if os.name == "nt":
        print(f'      cd "{HERE}"')
        print("      python -m venv .venv")
        print("      .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        print("      .venv\\Scripts\\python.exe run.py")
        print()
        print("  Or simply double-click  launch.bat  which does all of that for you.")
    else:
        print(f'      cd "{HERE}"')
        print("      python3 -m venv .venv")
        print("      .venv/bin/python -m pip install -r requirements.txt")
        print("      .venv/bin/python run.py")
        print()
        print("  Or run  ./launch.sh  which does all of that for you.")
    print()
    return 1


def relaunch_in_venv(interpreter: Path) -> int:
    """Re-run this script under the project venv and return its exit code."""
    print(f"Switching to the project environment: {interpreter}")
    environment = dict(os.environ, **{RELAUNCH_FLAG: "1"})
    try:
        completed = subprocess.run(
            [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]],
            env=environment,
            check=False,
        )
    except OSError as exc:
        print(f"Could not start the project environment: {exc}")
        return 1
    return completed.returncode


def is_frozen() -> bool:
    """True in a PyInstaller build, where dependencies are already bundled."""
    return bool(getattr(sys, "frozen", False))


def report_crash_frozen(error: BaseException) -> None:
    """Show a startup failure in a windowed build, which has no console."""
    import traceback

    detail = "".join(traceback.format_exception(type(error), error,
                                                error.__traceback__))
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("audix could not start")
        box.setText("audix hit an error while starting up.")
        try:
            from audix.utils import paths

            box.setInformativeText(f"A full log was written to:\n{paths.log_file()}")
        except Exception:  # noqa: BLE001
            pass
        box.setDetailedText(detail)
        box.exec()
    except Exception:  # noqa: BLE001 - Qt itself may be what failed
        pass


def main() -> int:
    # A frozen build carries its dependencies, has no project venv to fall back
    # on, and may have no console. Take the direct path.
    if is_frozen():
        try:
            from audix.__main__ import main as app_main

            return app_main()
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("audix").exception("Fatal startup error")
            report_crash_frozen(exc)
            return 1

    missing = missing_modules()

    if missing:
        interpreter = venv_python()
        already_tried = os.environ.get(RELAUNCH_FLAG) == "1"
        same_interpreter = (
            interpreter is not None
            and Path(sys.executable).resolve() == interpreter.resolve()
        )
        if interpreter is not None and not already_tried and not same_interpreter:
            return relaunch_in_venv(interpreter)
        code = report_missing(missing)
        pause()
        return code

    try:
        from audix.__main__ import main as app_main

        return app_main()
    except Exception:  # noqa: BLE001 - last resort: show the error, do not flash
        import traceback

        print("=" * 68)
        print(" audix crashed during startup")
        print("=" * 68)
        traceback.print_exc()
        try:
            from audix.utils import paths

            print(f"\nFull log: {paths.log_file()}")
        except Exception:  # noqa: BLE001
            pass
        pause()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
