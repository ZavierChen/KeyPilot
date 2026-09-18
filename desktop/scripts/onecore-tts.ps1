param(
    [Parameter(Mandatory = $true)][string]$VoiceName,
    [Parameter(Mandatory = $true)][string]$TextBase64,
    [ValidateRange(0.9, 1.1)][double]$SpeakingRate = 1.0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Windows.Forms
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

function Wait-WinRtOperation {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextBase64))
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object {
    $_.DisplayName -like "*$VoiceName*"
} | Select-Object -First 1
if (-not $voice) {
    throw "OneCore voice is not installed: $VoiceName"
}

$synthesizer = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$synthesizer.Voice = $voice
$synthesizer.Options.SpeakingRate = $SpeakingRate
$stream = Wait-WinRtOperation $synthesizer.SynthesizeTextToStreamAsync($text) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$reader = New-Object Windows.Storage.Streams.DataReader($stream)
[void](Wait-WinRtOperation $reader.LoadAsync([uint32]$stream.Size) ([uint32]))
$bytes = New-Object byte[] ([int]$stream.Size)
$reader.ReadBytes($bytes)

$tempPath = Join-Path ([IO.Path]::GetTempPath()) ("keypilot-onecore-" + [Guid]::NewGuid().ToString('N') + '.wav')
try {
    [IO.File]::WriteAllBytes($tempPath, $bytes)
    $player = New-Object System.Media.SoundPlayer($tempPath)
    $player.PlaySync()
}
finally {
    $reader.Dispose()
    $stream.Dispose()
    $synthesizer.Dispose()
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}
