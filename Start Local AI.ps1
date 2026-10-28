$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $project 'tools\ollama\runtime\ollama.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return }

try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
    return
} catch { }

$logs = Join-Path $project '.setup'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$previousModels = $env:OLLAMA_MODELS
$previousHost = $env:OLLAMA_HOST
try {
    $env:OLLAMA_MODELS = Join-Path $project 'models\ollama'
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    Start-Process -FilePath $exe -ArgumentList 'serve' -WorkingDirectory $project `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'ollama_stdout.log') `
        -RedirectStandardError (Join-Path $logs 'ollama_stderr.log') | Out-Null
} finally {
    $env:OLLAMA_MODELS = $previousModels
    $env:OLLAMA_HOST = $previousHost
}
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
        return
    } catch { }
}
Write-Warning 'Local AI did not start; AUTOCLIP AI will use its fallback selector.'
