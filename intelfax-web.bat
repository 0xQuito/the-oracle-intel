@echo off
rem Launch THE ORACLE in your web browser. Close this window (or Ctrl+C) to stop it.
rem Extra arguments are passed through, e.g. intelfax-web.bat --cols 100 --rows 40
cd /d "%~dp0"
py -m intelfax --web %*
