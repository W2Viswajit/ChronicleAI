$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = if (Test-Path .venv-local\Scripts\python.exe) { '.venv-local\Scripts\python.exe' } else { '.venv\Scripts\python.exe' }
if (!(Test-Path $python)) { throw 'Run setup.ps1 first.' }
Write-Host 'Open http://127.0.0.1:8000 once the server says startup complete. Stop with Ctrl+C.'
& $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
