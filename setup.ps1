$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = if (Test-Path .venv-local\Scripts\python.exe) { '.venv-local\Scripts\python.exe' } else { '.venv\Scripts\python.exe' }
function Test-Python($executable) {
    if (!(Test-Path $executable)) { return $false }
    try { & $executable --version *> $null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}
if (!(Test-Python $python)) {
    # Preserve the old environment if its original Python has been removed.
    $python = '.venv-local\Scripts\python.exe'
    $created = $false
    foreach ($version in @('3.13', '3.12', '3.11')) {
        try { py "-$version" --version *> $null } catch { continue }
        if ($LASTEXITCODE -eq 0) {
            py "-$version" -m venv .venv-local
            if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
            $created = $true
            break
        }
    }
    if (!$created) { throw 'Install Python 3.11, 3.12 or 3.13 for Windows, then rerun setup.ps1.' }
}
& $python -m pip install --no-cache-dir -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Share the error output.' }
if (!(Test-Path .env)) { Copy-Item .env.example .env }
& $python -c "from backend.config import MODE; raise SystemExit(0 if MODE == 'models' else 1)"
if ($LASTEXITCODE -eq 0) {
    & "$PSScriptRoot\setup-models.ps1"
}
Write-Host 'Setup complete. Optional: edit .env and add GEMINI_API_KEY. Run .\start.ps1.'
