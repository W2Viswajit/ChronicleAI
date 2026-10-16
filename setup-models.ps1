$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv\Scripts\python.exe)) { throw 'Run setup.ps1 first.' }
& .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-models.txt
if ($LASTEXITCODE -ne 0) { throw 'Model dependency installation failed.' }
& .\.venv\Scripts\python.exe -m spacy download en_core_web_sm
if ($LASTEXITCODE -ne 0) { throw 'spaCy model download failed.' }
& .\.venv\Scripts\python.exe -m scripts.download_models
if ($LASTEXITCODE -ne 0) { throw 'Model downloads failed. Check internet access.' }
Write-Host 'Models downloaded. Set NLP_MODE=models in .env and restart the app.'
