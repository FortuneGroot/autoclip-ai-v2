$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $project '.venv\Scripts\python.exe'
$ruleName = 'AUTOCLIP AI iPhone Local Wi-Fi'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'AUTOCLIP AI must be installed first.' }
$actualPython = (& $python -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $actualPython -PathType Leaf)) {
    throw 'Could not find the Python interpreter that receives network connections.'
}

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    if (@($existing).Count -ne 1) { throw 'Multiple firewall rules have this name; inspect them manually.' }
    $program = ($existing | Get-NetFirewallApplicationFilter).Program
    $port = ($existing | Get-NetFirewallPortFilter).LocalPort
    $remote = ($existing | Get-NetFirewallAddressFilter).RemoteAddress
    if (($program -ne $python -and $program -ne $actualPython) -or $port -ne '8765' -or
        $remote -ne 'LocalSubnet' -or $existing.Action -ne 'Allow' -or
        $existing.Direction -ne 'Inbound' -or [int]$existing.Profile -ne 6) {
        throw 'An existing rule with this name has different settings; inspect it manually.'
    }
    if ($program -eq $actualPython) {
        Write-Host 'AUTOCLIP AI local iPhone firewall rule is already in place.'
        exit 0
    }
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host 'Windows administrator approval is needed for a local Wi-Fi firewall rule.'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $MyInvocation.MyCommand.Path + '"'
    try {
        $elevated = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        exit $elevated.ExitCode
    } catch {
        Write-Error 'Windows administrator approval was not granted. The iPhone may be unable to connect.'
        exit 1
    }
}

if ($existing) {
    Set-NetFirewallRule -DisplayName $ruleName -Program $actualPython `
        -Description 'AUTOCLIP AI local iPhone access only; TCP 8765 from local subnet to the interpreter that listens for the app.' | Out-Null
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Enabled True `
        -Profile Private,Public -Protocol TCP -LocalPort 8765 -Program $actualPython `
        -RemoteAddress LocalSubnet -Description 'AUTOCLIP AI local iPhone access only; TCP 8765 from local subnet to the interpreter that listens for the app.' | Out-Null
}
Write-Host 'AUTOCLIP AI iPhone access is allowed from the local subnet only.'
