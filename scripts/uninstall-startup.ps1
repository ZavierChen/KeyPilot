$ErrorActionPreference = 'Stop'
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'KeyPilot.lnk'
if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    Write-Output "Removed startup shortcut: $shortcutPath"
} else {
    Write-Output 'KeyPilot startup shortcut is not installed.'
}

