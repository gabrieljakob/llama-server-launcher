@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHON=python"
where python >nul 2>&1 || set "PYTHON=py"
pushd "%SCRIPT_DIR%"
"%PYTHON%" -m launcher
popd
pause
