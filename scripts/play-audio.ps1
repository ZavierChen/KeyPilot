param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [double]$Volume = 1.0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
try {
    $player.Volume = [Math]::Max(0.0, [Math]::Min(1.0, $Volume))
    $player.Open([Uri]::new($Path))
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (-not $player.NaturalDuration.HasTimeSpan -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 30
    }
    $player.Play()
    if ($player.NaturalDuration.HasTimeSpan) {
        $duration = $player.NaturalDuration.TimeSpan.TotalMilliseconds
        $playDeadline = [DateTime]::UtcNow.AddMilliseconds($duration + 1500)
        while ($player.Position.TotalMilliseconds -lt ($duration - 40) -and [DateTime]::UtcNow -lt $playDeadline) {
            Start-Sleep -Milliseconds 35
        }
    } else {
        Start-Sleep -Seconds 30
    }
} finally {
    $player.Stop()
    $player.Close()
}
