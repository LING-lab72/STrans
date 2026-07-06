param(
    [string]$Port = "COM3",
    [int]$BaudRate = 115200,
    [int]$SerialSeconds = 15,
    [int[]]$PortsToScan = @(80, 81),
    [switch]$ProbeArpPorts
)

$ErrorActionPreference = "Continue"

Write-Host "== Serial devices =="
$serialDevices = Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue |
    Select-Object Status, FriendlyName, InstanceId
$serialDevices | ForEach-Object {
    Write-Host "$($_.Status)  $($_.FriendlyName)  $($_.InstanceId)"
}

Write-Host ""
Write-Host "== Active IPv4 interfaces =="
$activeInterfaces = Get-NetIPConfiguration |
    Where-Object { $_.IPv4Address -and $_.NetAdapter.Status -eq "Up" }

$activeInterfaces | ForEach-Object {
    $addr = $_.IPv4Address | Select-Object -First 1
    Write-Host "$($_.InterfaceAlias)  $($addr.IPv4Address)/$($addr.PrefixLength)"
}

Write-Host ""
Write-Host "== Serial boot log: $Port @ $BaudRate =="
try {
    $serial = New-Object System.IO.Ports.SerialPort $Port, $BaudRate, "None", 8, "One"
    $serial.ReadTimeout = 500
    $serial.Open()
    $deadline = (Get-Date).AddSeconds($SerialSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $line = $serial.ReadLine()
            Write-Host $line
        }
        catch [System.TimeoutException] {
        }
    }
}
catch {
    Write-Warning "Cannot read serial port $Port. $($_.Exception.Message)"
}
finally {
    if ($serial -and $serial.IsOpen) {
        $serial.Close()
    }
}

Write-Host ""
Write-Host "== ARP table =="
arp -a

Write-Host ""
Write-Host "== Fast HTTP port probe from ARP entries =="
$arpOutput = arp -a
$candidateIps = @()
foreach ($line in $arpOutput) {
    if ($line -match "^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+dynamic") {
        $candidateIps += $matches[1]
    }
}
$candidateIps = @($candidateIps | Sort-Object -Unique)

if ($ProbeArpPorts) {
    foreach ($ip in $candidateIps) {
        foreach ($scanPort in $PortsToScan) {
            $client = New-Object Net.Sockets.TcpClient
            try {
                $async = $client.BeginConnect($ip, $scanPort, $null, $null)
                if ($async.AsyncWaitHandle.WaitOne(300, $false)) {
                    $client.EndConnect($async)
                    Write-Host "OPEN $ip`:$scanPort"
                }
            }
            catch {
            }
            finally {
                $client.Close()
            }
        }
    }
}
else {
    Write-Host "Skipped. Add -ProbeArpPorts to test ports on ARP candidates."
}

Write-Host ""
Write-Host "== Candidate stream URLs =="
foreach ($ip in $candidateIps) {
    Write-Host "http://$ip/"
    Write-Host "http://$ip`:81/stream"
}
