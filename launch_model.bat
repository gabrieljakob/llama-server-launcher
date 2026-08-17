@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHON=python"
where python >nul 2>&1 || set "PYTHON=py"
"%PYTHON%" "%SCRIPT_DIR%model_launcher.py"
pause
