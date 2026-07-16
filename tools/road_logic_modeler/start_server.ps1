$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = if ($env:STRANS_PYTHON) { $env:STRANS_PYTHON } else { "python" }
& $python (Join-Path $root "server.py")
