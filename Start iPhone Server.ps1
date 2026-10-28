param([switch]$OpenApp, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
if ($OpenApp -and $NoBrowser) { throw 'Choose either OpenApp or NoBrowser.' }
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv\Scripts\python.exe'
$script = Join-Path $project 'mobile_server.py'
$setup = 'http://127.0.0.1:8765/setup'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install AUTOCLIP AI first.' }
& (Join-Path $project 'Start Local AI.ps1')

function Test-AutoclipServer {
    try {
        $reply = Invoke-WebRequest -Uri $setup -UseBasicParsing -TimeoutSec 2
        return ($reply.StatusCode -eq 200 -and $reply.Content -like '*AUTOCLIP AI for iPhone*')
    } catch { return $false }
}

if (-not (Test-AutoclipServer)) {
    $logs = Join-Path $project '.setup'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $stdout = Join-Path $logs 'iphone_server_stdout.log'
    $stderr = Join-Path $logs 'iphone_server_stderr.log'
    $quotedScript = '"' + $script + '"'
    Start-Process -FilePath $python -ArgumentList $quotedScript -WorkingDirectory $project `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 300
        if (Test-AutoclipServer) { $ready = $true; break }
    }
    if (-not $ready) {
        $detail = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Tail 8 | Out-String } else { '' }
        throw "AUTOCLIP AI iPhone server could not start. $detail"
    }
}

if ($NoBrowser) {
    Write-Host 'AUTOCLIP AI is running in the background.'
} elseif ($OpenApp) {
    $secretFile = Join-Path $project '.mobile_secret'
    if (-not (Test-Path -LiteralPath $secretFile -PathType Leaf)) {
        throw 'AUTOCLIP AI access key is missing. Restart the launcher.'
    }
    $key = (Get-Content -LiteralPath $secretFile -Raw -Encoding Ascii).Trim()
    if ($key -cnotmatch '^[A-Za-z0-9_-]{24,}$') {
        throw 'AUTOCLIP AI access key is invalid.'
    }
    $destination = 'http://127.0.0.1:8765/?key=' + [Uri]::EscapeDataString($key)
    Start-Process -FilePath $destination
    Write-Host 'AUTOCLIP AI is open in your browser.'
} else {
    Start-Process -FilePath $setup
    Write-Host 'AUTOCLIP AI is running in the background. The QR setup page is open.'
}
