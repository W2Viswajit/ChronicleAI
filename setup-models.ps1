$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = if (Test-Path .venv-local\Scripts\python.exe) { '.venv-local\Scripts\python.exe' } else { '.venv\Scripts\python.exe' }
if (!(Test-Path $python)) { throw 'Run setup.ps1 first.' }
& $python -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& $python -m pip install --no-cache-dir -r requirements-models.txt
if ($LASTEXITCODE -ne 0) { throw 'Model dependency installation failed.' }
& $python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('en_core_web_sm') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $python -m spacy download en_core_web_sm
    if ($LASTEXITCODE -ne 0) { throw 'spaCy model download failed.' }
}
& $python -m scripts.download_models
if ($LASTEXITCODE -ne 0) { throw 'Model downloads failed. Check internet access.' }
Write-Host 'Models downloaded. Set NLP_MODE=models in .env and restart the app.'
