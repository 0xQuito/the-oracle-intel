@echo off
rem Launch THE ORACLE in this console window. Extra arguments are passed through (e.g. --wide).
cd /d "%~dp0"
py -m intelfax %*
