@echo off
rem Starts the app with Administrator rights (needed to type into apps/games
rem that themselves run as Administrator).
setlocal EnableExtensions
set "SCRIPT=%~dp0FKeyAutomator.pyw"
set "PYW="
set "ARGS="
for /f "delims=" %%I in ('where pyw.exe 2^>nul') do if not defined PYW set "PYW=%%I" & set "ARGS=-3 "
if not defined PYW (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
)
if not defined PYW (
    echo Python 3 was not found. Run install.bat first.
    pause
    exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath '%PYW%' -ArgumentList '%ARGS%\"%SCRIPT%\"' -Verb RunAs"
