#!/usr/bin/env python3
"""Build the audix Windows executable.

    python packaging/build_exe.py                 # full build, one folder
    python packaging/build_exe.py --lite          # no browser, much smaller
    python packaging/build_exe.py --onefile       # single .exe (see caveat)

One-folder is the default because QtWebEngine is fragile in one-file mode: the
bootloader unpacks several hundred megabytes to a temp directory on every launch,
which is slow, and QtWebEngineProcess.exe does not reliably locate its resources
from there. One-file is offered for the lite build, where there is no Chromium.

FFmpeg is not bundled. The app fetches a platform-correct static build into
~/.audix/bin on first run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        pass
    print("PyInstaller is not installed. Installing it now...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"], check=False)
    return result.returncode == 0


def remove_stale(target: Path, attempts: int = 4) -> bool:
    """Delete a previous build, tolerating transient Windows file locks.

    Two things routinely hold files here: a still-running copy of the app, and
    cloud-sync clients (OneDrive, Dropbox) that open files to upload them. Both
    release quickly, so retry with backoff before giving up - and when giving
    up, say what to do rather than dumping a traceback.
    """
    for attempt in range(attempts):
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            return True
        except PermissionError as exc:
            if attempt == attempts - 1:
                print(
                    f"\nCould not remove the previous build:\n  {exc}\n\n"
                    "Something is holding those files open. Usually one of:\n"
                    "  - audix is still running (close it, including any\n"
                    "    QtWebEngineProcess.exe left behind)\n"
                    "  - a cloud-sync client (OneDrive/Dropbox) is uploading\n"
                    "    the folder; pause syncing or wait a moment\n"
                    "  - antivirus is scanning the freshly written files\n\n"
                    f"Then run the build again, or delete {target} by hand.",
                    file=sys.stderr,
                )
                return False
            wait = 2 * (attempt + 1)
            print(f"  locked; retrying in {wait}s "
                  f"(attempt {attempt + 2} of {attempts})")
            time.sleep(wait)
        except OSError as exc:
            print(f"\nCould not remove the previous build: {exc}", file=sys.stderr)
            return False
    return False


def build_icon() -> None:
    result = subprocess.run([sys.executable, str(HERE / "make_icon.py")], check=False)
    if result.returncode != 0:
        print("  (continuing without a custom icon)")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the audix executable.")
    parser.add_argument("--lite", action="store_true",
                        help="exclude QtWebEngine; the Browser tab degrades to a "
                             "placeholder and the build shrinks dramatically")
    parser.add_argument("--onefile", action="store_true",
                        help="produce a single .exe instead of a folder")
    parser.add_argument("--name", default=None, help="output name")
    parser.add_argument("--keep-build", action="store_true",
                        help="keep PyInstaller's intermediate build directory")
    args = parser.parse_args(argv)

    if args.onefile and not args.lite:
        print("NOTE: one-file with QtWebEngine unpacks ~400 MB on every launch and\n"
              "      QtWebEngineProcess often fails to find its resources there.\n"
              "      Consider --lite --onefile, or a one-folder full build.\n")

    name = args.name or ("audix-lite" if args.lite else "audix")

    if not ensure_pyinstaller():
        print("Could not install PyInstaller.", file=sys.stderr)
        return 1

    print("Generating icon...")
    build_icon()

    env = dict(os.environ)
    env["AUDIX_WITH_BROWSER"] = "0" if args.lite else "1"
    env["AUDIX_ONEFILE"] = "1" if args.onefile else "0"
    env["AUDIX_APP_NAME"] = name

    dist = ROOT / "dist"
    work = ROOT / "build"
    target = dist / (f"{name}.exe" if args.onefile else name)
    if target.exists():
        print(f"Removing previous build at {target}")
        if not remove_stale(target):
            return 1

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(dist),
        "--workpath", str(work),
        str(HERE / "audix.spec"),
    ]

    variant = "lite (no browser)" if args.lite else "full (with browser)"
    layout = "one file" if args.onefile else "one folder"
    # Pure ASCII: this prints to a console whose codepage is not guaranteed.
    print(f"\nBuilding audix  |  {variant}  |  {layout}")
    print("This takes a few minutes.\n")

    started = time.time()
    result = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
    elapsed = time.time() - started

    if result.returncode != 0:
        print(f"\nBuild FAILED after {elapsed:.0f}s.", file=sys.stderr)
        return result.returncode

    if not target.exists():
        print(f"\nBuild reported success but {target} is missing.", file=sys.stderr)
        return 1

    if not args.keep_build:
        shutil.rmtree(work, ignore_errors=True)

    size = tree_size(target)
    print("\n" + "=" * 62)
    print(f"  Built in {elapsed:.0f}s")
    print(f"  Output : {target}")
    print(f"  Size   : {human(size)}")
    if not args.onefile:
        print(f"  Launch : {target / (name + '.exe')}")
    print("=" * 62)
    print("\nFFmpeg is downloaded on first run into ~/.audix/bin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
