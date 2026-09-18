$ErrorActionPreference = 'Stop'
$taskName = 'KeyPilot'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output 'Removed the KeyPilot scheduled task.'
} else {
    Write-Output 'The KeyPilot scheduled task is not installed.'
}

& (Join-Path $PSScriptRoot 'stop.ps1')
