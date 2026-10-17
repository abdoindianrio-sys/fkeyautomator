@echo off
rem Starts the app without installing it.
setlocal
set "SCRIPT=%~dp0FKeyAutomator.pyw"
where pyw.exe >nul 2>nul && (
    start "" pyw.exe -3 "%SCRIPT%"
    exit /b 0
)
where pythonw.exe >nul 2>nul && (
    start "" pythonw.exe "%SCRIPT%"
    exit /b 0
)
echo Python 3 was not found. Run install.bat first, or install Python from https://www.python.org
pause
