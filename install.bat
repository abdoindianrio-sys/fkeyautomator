@echo off
setlocal EnableExtensions
title FKey Automator - Installer
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\FKeyAutomator"

echo.
echo  ==============================================
echo    FKey Automator - Installer
echo  ==============================================
echo.

rem ---- never delete the folder we are running from ----
if /i "%SRC%"=="%DEST%\" (
    echo [!] Run install.bat from the extracted ZIP folder, not from the install folder.
    goto :fail
)
if not exist "%SRC%fkeyautomator\app.py" (
    echo [!] Extract the whole ZIP first, then run install.bat from the extracted folder.
    goto :fail
)

rem ---- 1. find Python 3 ----
set "PYCMD="
py -3 -c "import sys" >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
    python -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD goto :nopython

%PYCMD% -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [!] Python 3.9 or newer is required. Please update Python from https://www.python.org
    goto :fail
)
%PYCMD% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [!] Python is installed but Tkinter is missing.
    echo     Re-run the Python installer, choose Modify, and tick "tcl/tk and IDLE".
    goto :fail
)
echo [OK] Found Python: %PYCMD%

rem ---- 2. find the windowless launcher (pyw / pythonw) ----
set "PYW="
set "PYW_ARGS="
set "LAUNCHER_FLAG="
if "%PYCMD%"=="py -3" (
    for /f "delims=" %%I in ('where pyw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
    if defined PYW (
        set "PYW_ARGS=-3 "
        set "LAUNCHER_FLAG=-UseLauncher"
    )
)
if not defined PYW (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
)
if not defined PYW (
    echo [!] Could not find pyw.exe or pythonw.exe.
    goto :fail
)

rem ---- 3. copy files ----
echo [..] Installing to: %DEST%
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%\tools" || goto :fail
xcopy "%SRC%fkeyautomator" "%DEST%\fkeyautomator\" /E /I /Y /Q >nul || goto :fail
copy /Y "%SRC%FKeyAutomator.pyw" "%DEST%\" >nul || goto :fail
copy /Y "%SRC%uninstall.bat" "%DEST%\" >nul
copy /Y "%SRC%run_as_admin.bat" "%DEST%\" >nul
copy /Y "%SRC%tools\make_shortcuts.ps1" "%DEST%\tools\" >nul || goto :fail
if exist "%DEST%\fkeyautomator\__pycache__" rmdir /s /q "%DEST%\fkeyautomator\__pycache__"

rem ---- 4. shortcuts (Desktop + Start menu) ----
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\tools\make_shortcuts.ps1" -Target "%PYW%" -Script "%DEST%\FKeyAutomator.pyw" -WorkDir "%DEST%" -Icon "%DEST%\fkeyautomator\assets\app.ico" %LAUNCHER_FLAG%
if errorlevel 1 (
    echo [!] Could not create shortcuts. You can still start the app with:
    echo     "%DEST%\FKeyAutomator.pyw"
) else (
    echo [OK] Shortcuts created on the Desktop and in the Start menu.
)

echo.
echo  Installed successfully.
echo  Start it from the "FKey Automator" shortcut.
echo  Tip: if your game or app runs as Administrator, use the
echo       "restart as administrator" link inside the app.
echo.
choice /C YN /M "Start FKey Automator now"
if errorlevel 2 goto :end
start "" "%PYW%" %PYW_ARGS%"%DEST%\FKeyAutomator.pyw"
goto :end

:nopython
echo [!] Python 3 was not found on this PC.
where winget >nul 2>nul
if errorlevel 1 (
    echo     Install Python 3.12 or newer from https://www.python.org/downloads/
    echo     and keep "tcl/tk and IDLE" ticked, then run install.bat again.
    goto :fail
)
echo.
choice /C YN /M "Install Python 3.12 now using winget"
if errorlevel 2 (
    echo     Install Python from https://www.python.org/downloads/ and run install.bat again.
    goto :fail
)
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo  Python was installed. Please CLOSE this window and run install.bat again.
goto :end

:fail
echo.
echo  Installation did not complete.
endlocal
pause
exit /b 1

:end
endlocal
pause
exit /b 0
