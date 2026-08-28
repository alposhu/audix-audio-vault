#!/usr/bin/env bash
# ===========================================================================
#  audix launcher for macOS and Linux.
#
#  Creates the project environment on first run, installs dependencies, then
#  starts the app. Run with:  ./launch.sh
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV_PY="$HERE/.venv/bin/python"

die() {
    echo
    echo "  ERROR: $1"
    echo
    exit 1
}

if [ ! -x "$VENV_PY" ]; then
    echo
    echo "  Setting up audix for the first time. This happens only once."
    echo

    BOOTSTRAP=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BOOTSTRAP="$candidate"
            break
        fi
    done
    [ -n "$BOOTSTRAP" ] || die "Python 3.9+ was not found. Install it and try again."

    echo "  Creating virtual environment..."
    "$BOOTSTRAP" -m venv "$HERE/.venv" \
        || die "Could not create the virtual environment in $HERE/.venv"
fi

# Only reinstall when something is actually missing, so normal starts are fast.
if ! "$VENV_PY" -c "import PySide6, yt_dlp, mutagen, requests" >/dev/null 2>&1; then
    echo "  Installing dependencies (this downloads about 250 MB, one time only)..."
    echo
    "$VENV_PY" -m pip install --upgrade pip --quiet
    "$VENV_PY" -m pip install -r "$HERE/requirements.txt" \
        || die "Dependency installation failed. Check your internet connection."
fi

echo "  Starting audix..."
echo
exec "$VENV_PY" "$HERE/run.py" "$@"
