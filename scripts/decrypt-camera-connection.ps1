[CmdletBinding()]
param(
    [ValidateSet('STREAM_ID', 'SRT_URL', 'RTSP_URL', 'RTMP_URL', 'WHIP_URL', 'WHEP_URL', 'HTTP_STREAM_URL', 'HLS_URL', 'ALL')]
    [string]$Field = 'STREAM_ID',
    [string]$EncryptedFile = (Join-Path $PSScriptRoot '..\secret\camera-connection.age'),
    [string]$IdentityFile = (Join-Path $PSScriptRoot '..\secret\camera-connection.key')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$age = Get-Command age -ErrorAction SilentlyContinue
if (-not $age) {
    $age = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Recurse -Filter 'age.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $age) {
    throw 'age was not found. Install it with: winget install --id FiloSottile.age --exact'
}
$ageExecutable = if ($age.PSObject.Properties.Name -contains 'Path') { $age.Path } else { $age.FullName }
$encryptedPath = [System.IO.Path]::GetFullPath($EncryptedFile)
$identityPath = [System.IO.Path]::GetFullPath($IdentityFile)

if (-not (Test-Path -LiteralPath $encryptedPath -PathType Leaf)) {
    throw "Encrypted credential package was not found: $encryptedPath"
}

if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
    throw "Local age identity was not found: $identityPath"
}

$values = @{}
& $ageExecutable --decrypt --identity $identityPath $encryptedPath | ForEach-Object {
    if ($_ -match '^(?<key>[A-Z0-9_]+)=(?<value>.*)$') {
        $values[$Matches.key] = $Matches.value
    }
}

if ($LASTEXITCODE -ne 0) {
    throw 'Credential decryption failed.'
}

switch ($Field) {
    'STREAM_ID' {
        foreach ($key in @('STREAM_PATH', 'PUBLISH_USER', 'PUBLISH_PASSWORD')) {
            if (-not $values.ContainsKey($key)) {
                throw "Decrypted credentials are missing $key."
            }
        }
        "publish:$($values.STREAM_PATH):$($values.PUBLISH_USER):$($values.PUBLISH_PASSWORD)"
    }
    { $_ -in 'HTTP_STREAM_URL', 'HLS_URL' } {
        foreach ($key in @('STREAM_DOMAIN', 'STREAM_PATH', 'READ_USER', 'READ_PASSWORD')) {
            if (-not $values.ContainsKey($key)) {
                throw "Decrypted credentials are missing $key."
            }
        }
        "http://$($values.READ_USER):$($values.READ_PASSWORD)@$($values.STREAM_DOMAIN):8888/$($values.STREAM_PATH)/index.m3u8"
    }
    'ALL' {
        $values.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }
    }
    default {
        if (-not $values.ContainsKey($Field)) {
            throw "Decrypted credentials are missing $Field."
        }
        $values[$Field]
    }
}
