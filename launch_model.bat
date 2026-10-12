@echo off
setlocal
where uv >nul 2>&1 || (
  echo uv is not installed. Run install.ps1, or see https://docs.astral.sh/uv/
  pause
  exit /b 1
)
uv run --project "%~dp0." llama-launcher %*
pause
