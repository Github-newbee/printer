$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$port = if ($env:PORT) { $env:PORT } else { "8080" }
$listen = "*:$port"

Write-Host "Print service is starting..."
Write-Host ""
Write-Host "Local access : http://localhost:$port"

$addresses = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
    } |
    Select-Object -ExpandProperty IPAddress -Unique

foreach ($address in $addresses) {
    Write-Host "LAN access   : http://$address`:$port"
}

Write-Host ""
Write-Host "Press Ctrl+C to stop."
Write-Host ""

uv run waitress-serve --listen=$listen app:app
