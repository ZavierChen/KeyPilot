param([string]$VoiceName = 'Huihui')

$ErrorActionPreference = 'Stop'
$voice = New-Object -ComObject SAPI.SpVoice
$preferred = $voice.GetVoices() | Where-Object {
    $_.GetDescription() -like "*$VoiceName*"
} | Select-Object -First 1
if (-not $preferred) {
    $preferred = $voice.GetVoices() | Where-Object {
        $_.GetDescription() -match 'Huihui|Chinese|中文'
    } | Select-Object -First 1
}
if ($preferred) {
    $voice.Voice = $preferred
}
$voice.Rate = 1

while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ($line -eq '__EXIT__') {
        break
    }
    try {
        $bytes = [Convert]::FromBase64String($line)
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        if ($text) {
            [void]$voice.Speak($text)
        }
    }
    catch {
        continue
    }
}
