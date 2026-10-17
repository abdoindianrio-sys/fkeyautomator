@echo off
rem OPTIONAL: builds a single-file FKeyAutomator.exe with PyInstaller (needs internet once).
rem Note: unsigned PyInstaller executables are sometimes flagged by antivirus software.
setlocal EnableExtensions
cd /d "%~dp0"
py -3 -m pip install --upgrade pyinstaller || goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name FKeyAutomator --icon "fkeyautomator\assets\app.ico" --add-data "fkeyautomator\assets;fkeyautomator\assets" FKeyAutomator.pyw || goto :fail
echo.
echo Built: %~dp0dist\FKeyAutomator.exe
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
