$ErrorActionPreference = 'Stop'
$sourceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\KeyPilot'
$desktopDir = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDir 'KeyPilot.lnk'
$taskName = 'KeyPilot'
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$settingsPath = Join-Path $installDir 'assistant-settings.json'
$preservedSettings = $null
if (Test-Path -LiteralPath $settingsPath) {
    $preservedSettings = [System.IO.File]::ReadAllText($settingsPath)
}

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}
$oldProcesses = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object {
        $_.CommandLine -match 'keypilot[\\/]main.py' -or
        $_.CommandLine -match 'keypilot\.assistant_app' -or
        $_.CommandLine -match 'keypilot\.chat_bridge' -or
        $_.CommandLine -match 'keypilot\.marvis_bridge' -or
        $_.CommandLine -match 'keypilot\.time_worker'
    }
foreach ($process in $oldProcesses) {
    Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
}

[void](New-Item -ItemType Directory -Path $installDir -Force)
Get-ChildItem -LiteralPath $sourceDir -Force | Where-Object {
    $_.Name -notin @('__pycache__', '.git')
} | Copy-Item -Destination $installDir -Recurse -Force
if ($null -ne $preservedSettings) {
    [System.IO.File]::WriteAllText($settingsPath, $preservedSettings, [System.Text.UTF8Encoding]::new($false))
}

$installedMain = Join-Path $installDir 'keypilot\main.py'
$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument ('"{0}"' -f $installedMain) `
    -WorkingDirectory $installDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'KeyPilot Copilot-key portal and resident keyboard service' `
    -Force | Out-Null

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m keypilot.launcher'
$shortcut.WorkingDirectory = $installDir
$shortcut.IconLocation = (Join-Path $installDir 'assets\keypilot.ico')
$shortcut.Description = 'KeyPilot Copilot 按键门户'
$shortcut.Save()

Start-ScheduledTask -TaskName $taskName
Write-Output "Installed: $installDir"
Write-Output "Desktop shortcut: $shortcutPath"
Write-Output "Startup task: $taskName"
