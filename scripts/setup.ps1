param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        if ($Python -eq 'py') { & $Python -3.12 -m venv .venv }
        else { & $Python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 with tkinter is required.' }
    }
    & '.venv/Scripts/python.exe' -m pip install -r requirements/repro-windows-py312.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & '.venv/Scripts/python.exe' -m pip install --no-deps --no-build-isolation -e .
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
    & '.venv/Scripts/python.exe' scripts/keypilot.py doctor
    if ($LASTEXITCODE -ne 0) { throw 'Startup checks failed.' }
    Write-Host 'Ready. Run: .\.venv\Scripts\python.exe scripts/keypilot.py gui'
} finally { Pop-Location }
