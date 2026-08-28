@echo off
rem ==========================================================================
rem  audix launcher for Windows.
rem
rem  Double-click this file. It creates the project environment on first run,
rem  installs dependencies, starts the app, and (importantly) stays open if
rem  anything goes wrong so the error is readable.
rem ==========================================================================
setlocal
cd /d "%~dp0"
title audix

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto have_env

echo.
echo   Setting up audix for the first time. This happens only once.
echo.

set "BOOTSTRAP="
py -3 --version >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=py -3"
if defined BOOTSTRAP goto make_venv

python --version >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=python"
if defined BOOTSTRAP goto make_venv

goto no_python

:make_venv
echo   Creating virtual environment...
%BOOTSTRAP% -m venv "%~dp0.venv"
if errorlevel 1 goto venv_failed

:have_env
rem Only reinstall when something is actually missing, so normal starts are fast.
"%VENV_PY%" -c "import PySide6, yt_dlp, mutagen, requests" >nul 2>&1
if not errorlevel 1 goto start_app

echo   Installing dependencies (this downloads about 250 MB, one time only)...
echo.
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto pip_failed

:start_app
echo   Starting audix...
echo.
"%VENV_PY%" "%~dp0run.py" %*
if errorlevel 1 goto app_failed
exit /b 0

rem --------------------------------------------------------------- failures
:no_python
echo.
echo   ERROR: Python was not found on this system.
echo.
echo   Install Python 3.9 or newer from https://www.python.org/downloads/
echo   During installation, tick "Add python.exe to PATH".
echo.
pause
exit /b 1

:venv_failed
echo.
echo   ERROR: Could not create the virtual environment in:
echo     %~dp0.venv
echo.
echo   Check that you have write permission to this folder, then try again.
echo.
pause
exit /b 1

:pip_failed
echo.
echo   ERROR: Dependency installation failed.
echo.
echo   Check your internet connection and any proxy or firewall settings,
echo   then run this file again.
echo.
pause
exit /b 1

:app_failed
echo.
echo   audix exited with an error. See the log for details:
echo     %USERPROFILE%\.audix\logs\audix.log
echo.
pause
exit /b 1
