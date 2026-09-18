$processes = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object {
        $_.CommandLine -match 'keypilot[\\/]main.py' -or
        $_.CommandLine -match 'keypilot\.assistant_app' -or
        $_.CommandLine -match 'keypilot\.chat_bridge' -or
        $_.CommandLine -match 'keypilot\.time_worker'
    }
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId
    Write-Output "Stopped KeyPilot process $($process.ProcessId)"
}
if (-not $processes) {
    Write-Output 'No background KeyPilot process was found.'
}
