# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for audix.

Two variants, selected with the AUDIX_WITH_BROWSER environment variable:

  full  (default) - includes QtWebEngine, so the in-app YouTube browser works.
                    Large, because it carries a Chromium runtime.
  lite  (=0)      - excludes QtWebEngine. Much smaller; the Browser tab shows
                    its existing "not available" placeholder and every other
                    feature is unaffected.

FFmpeg is deliberately NOT bundled. audix downloads a platform-correct static
build into ~/.audix/bin on first run, which keeps the installer small and lets
the codec set update independently of the app.

Build through packaging/build_exe.py rather than invoking this directly; that
script sets the environment variables this file reads.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# A spec is exec'd without __file__, but PyInstaller injects SPECPATH. Guard
# rather than defaulting, so __file__ is never evaluated when it is absent.
if "SPECPATH" in globals():
    PROJECT_ROOT = Path(SPECPATH).parent           # noqa: F821 - injected
else:                                              # pragma: no cover - editors
    PROJECT_ROOT = Path.cwd()

WITH_BROWSER = os.environ.get("AUDIX_WITH_BROWSER", "1") != "0"
ONEFILE = os.environ.get("AUDIX_ONEFILE", "0") == "1"
APP_NAME = os.environ.get("AUDIX_APP_NAME", "audix")

# --------------------------------------------------------------------- inputs
datas = []
binaries = []
hiddenimports = []

# yt-dlp resolves extractors dynamically, so static analysis misses almost all
# of them. Collect the package wholesale or most URLs fail at runtime.
for collector in ("yt_dlp", "mutagen"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(collector)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# sounddevice ships the PortAudio DLL as package data; without it, real-time
# preview silently reports "backend unavailable" in the built app.
datas += collect_data_files("sounddevice")
hiddenimports += ["sounddevice", "_sounddevice"]

# requests' CA bundle.
datas += collect_data_files("certifi")

hiddenimports += collect_submodules("numpy")
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",      # QNetworkCookie, used by the cookie bridge
]

if WITH_BROWSER:
    hiddenimports += [
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        # QtWebEngine's own dependencies, pulled in indirectly.
        "PySide6.QtWebChannel",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtOpenGL",
        "PySide6.QtPositioning",
        "PySide6.QtPrintSupport",
    ]

# ------------------------------------------------------------------ exclusions
# Trim Qt modules audix never touches. This is where most of the size saving
# lives; PySide6 otherwise ships a very large surface area.
excludes = [
    "tkinter", "unittest", "pydoc_data", "test",
    "matplotlib", "scipy", "pandas", "PIL", "IPython",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort",
    "PySide6.QtSerialBus", "PySide6.QtSensors", "PySide6.QtTest",
    "PySide6.QtSql", "PySide6.QtHelp", "PySide6.QtDesigner",
    "PySide6.QtUiTools", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtRemoteObjects",
    "PySide6.QtTextToSpeech", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtNetworkAuth", "PySide6.QtWebSockets",
    # NOTE: never exclude shiboken6 - PySide6 imports it at module load, so
    # excluding it produces a build that dies on the very first import.
]

# QtMultimedia is excluded only in the lite build. QtWebEngineCore links against
# it on some PySide6 builds, and excluding it there yields an executable that
# fails to load the browser at runtime rather than failing loudly at build time.
if not WITH_BROWSER:
    excludes += ["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
                 "PySide6.QtSpatialAudio"]

if not WITH_BROWSER:
    # The Browser tab degrades to an explanatory placeholder without these.
    excludes += [
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
        "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
        "PySide6.QtQml", "PySide6.QtPositioning",
    ]

# ---------------------------------------------------------------------- build
a = Analysis(
    [str(PROJECT_ROOT / "run.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# PyInstaller 6 removed bytecode encryption, so PYZ takes no cipher argument.
# QtWebEngine ships Chrome DevTools resources: 72 MB of `.debug.pak` plus an
# 11 MB release pak. audix never opens an inspector, so both are dead weight -
# about 14% of the whole build. Everything else WebEngine needs is kept.
_DEVTOOLS = "devtools_resources"
_before = len(a.datas)
a.datas = [entry for entry in a.datas if _DEVTOOLS not in entry[0].replace("\\", "/")]
print(f"[audix] dropped {_before - len(a.datas)} DevTools resource file(s)")

pyz = PYZ(a.pure)

icon_path = PROJECT_ROOT / "packaging" / "audix.ico"
icon = str(icon_path) if icon_path.is_file() else None

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,          # windowed: run.py shows a dialog on failure
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
