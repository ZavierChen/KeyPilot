$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$residentTask = Get-ScheduledTask -TaskName 'KeyPilot' -ErrorAction SilentlyContinue
if ($residentTask) {
    Stop-ScheduledTask -TaskName 'KeyPilot' -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    Start-ScheduledTask -TaskName 'KeyPilot'
    exit 0
}

$stopScript = Join-Path $projectDir 'scripts\stop.ps1'
if (Test-Path -LiteralPath $stopScript) {
    & $stopScript | Out-Null
}
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$env:PYTHONPATH = $projectDir
$scriptPath = Join-Path $projectDir 'keypilot\main.py'
Start-Process -FilePath $pythonw -ArgumentList @("`"$scriptPath`"") -WorkingDirectory $projectDir -WindowStyle Hidden
