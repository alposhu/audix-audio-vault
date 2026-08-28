@echo off
rem ==========================================================================
rem  Build the audix Windows executable.
rem
rem  Double-click for a full build, or pass flags:
rem     build_exe.bat --lite       smaller build, no in-app browser
rem     build_exe.bat --onefile    single .exe instead of a folder
rem ==========================================================================
setlocal
cd /d "%~dp0"
title Building audix

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto have_env

echo.
echo   The project environment is missing. Run launch.bat once first so the
echo   dependencies are installed, then build.
echo.
pause
exit /b 1

:have_env
"%VENV_PY%" "%~dp0packaging\build_exe.py" %*
if errorlevel 1 goto failed

echo.
echo   Build complete. See the dist folder.
echo.
pause
exit /b 0

:failed
echo.
echo   Build failed. Scroll up for the error.
echo.
pause
exit /b 1
