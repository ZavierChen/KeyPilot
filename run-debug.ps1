$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $projectDir
& python (Join-Path $projectDir 'keypilot\main.py') --debug

