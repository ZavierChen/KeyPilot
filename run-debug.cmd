@echo off
setlocal
set "PYTHONPATH=%~dp0"
python "%~dp0keypilot\main.py" --debug
if errorlevel 1 pause

