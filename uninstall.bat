@echo off
setlocal EnableExtensions
title FKey Automator - Uninstall
set "DEST=%LOCALAPPDATA%\FKeyAutomator"

echo.
echo  This removes FKey Automator from this PC.
echo  Close the app first if it is running.
echo.
choice /C YN /M "Continue"
if errorlevel 2 exit /b 0

if exist "%DEST%\tools\make_shortcuts.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\tools\make_shortcuts.ps1" -Remove
)

choice /C YN /M "Also delete the saved settings"
if not errorlevel 2 (
    if exist "%APPDATA%\FKeyAutomator" rmdir /s /q "%APPDATA%\FKeyAutomator"
)

rem The program folder contains this script, so delete it just after we exit.
if exist "%DEST%" (
    start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '%DEST%' -Recurse -Force -ErrorAction SilentlyContinue"
)
echo.
echo  Done.
pause
exit /b 0
