@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0judge_setup.ps1"
if errorlevel 1 (
  echo.
  echo JUDGE_SETUP=FAIL
  exit /b 1
)
exit /b 0
