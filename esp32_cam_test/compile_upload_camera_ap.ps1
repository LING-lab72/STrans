param(
    [string]$Port = "COM3",
    [string]$Fqbn = "esp32:esp32:esp32cam"
)

$ErrorActionPreference = "Stop"
$env:Path = "C:\Program Files\Arduino CLI;" + $env:Path

$sketch = Join-Path $PSScriptRoot "CameraWebServerAP"

Write-Host "== Compile CameraWebServerAP =="
arduino-cli compile --fqbn $Fqbn $sketch

Write-Host ""
Write-Host "== Upload CameraWebServerAP to $Port =="
arduino-cli upload -p $Port --fqbn $Fqbn $sketch

Write-Host ""
Write-Host "== Serial monitor hint =="
Write-Host "Run: arduino-cli monitor -p $Port -c baudrate=115200"
