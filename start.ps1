$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv\Scripts\python.exe)) { throw 'Run setup.ps1 first.' }
Write-Host 'Open http://127.0.0.1:8000 once the server says startup complete. Stop with Ctrl+C.'
& .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
