param([Parameter(Mandatory=$true)][string]$ProjectPath)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $ProjectPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $target 'backend\retrieval.py'))) {
    throw 'Select the ChronicleAI project folder containing backend\retrieval.py.'
}
$backup = Join-Path $target ('runtime\retrieval-patch-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$files = @('backend\news_search.py', 'backend\retrieval.py', 'scripts\verify_news_search.py', 'tests\test_news_search.py', 'docs\news-search-fix.md')
foreach ($relative in $files) {
    $source = Join-Path $PSScriptRoot $relative
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing patch file: $relative. Extract the complete ZIP first." }
}
foreach ($relative in $files) {
    $destination = Join-Path $target $relative
    if (Test-Path -LiteralPath $destination) {
        $saved = Join-Path $backup $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $saved) | Out-Null
        Copy-Item -LiteralPath $destination -Destination $saved
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $relative) -Destination $destination -Force
}
Write-Host "Retrieval patch installed. Existing files backed up at: $backup"
Write-Host 'Restart the backend with start.ps1.'
Write-Host 'To verify from your project folder: .\.venv\Scripts\python.exe -m scripts.verify_news_search --gap 35'
