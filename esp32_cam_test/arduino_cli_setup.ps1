$ErrorActionPreference = "Stop"

Write-Host "== Arduino CLI version =="
arduino-cli version

Write-Host ""
Write-Host "== Initialize Arduino CLI config =="
arduino-cli config init --overwrite

Write-Host ""
Write-Host "== Add ESP32 board manager URL =="
arduino-cli config add board_manager.additional_urls "https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json"

Write-Host ""
Write-Host "== Update core index =="
arduino-cli core update-index

Write-Host ""
Write-Host "== Install ESP32 core =="
arduino-cli core install esp32:esp32

Write-Host ""
Write-Host "== Connected boards =="
arduino-cli board list

Write-Host ""
Write-Host "== ESP32-CAM FQBN candidates =="
arduino-cli board listall esp32cam
