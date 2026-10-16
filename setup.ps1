$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 for Windows, then rerun setup.ps1.' }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Share the error output.' }
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Write-Host 'Setup complete. Optional: edit .env and add GEMINI_API_KEY. Run .\start.ps1.'
