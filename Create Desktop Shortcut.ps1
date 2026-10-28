$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $project 'Open AUTOCLIP AI.vbs'
$icon = Join-Path $project 'mobile\autoclip.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'AUTOCLIP AI launcher is missing.' }
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw 'AUTOCLIP AI icon is missing.' }
if ([string]::IsNullOrWhiteSpace($desktop) -or -not (Test-Path -LiteralPath $desktop -PathType Container)) {
    throw 'The Windows Desktop folder could not be found.'
}
$destination = Join-Path $desktop 'AUTOCLIP AI.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($destination)
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + $launcher + '"'
$shortcut.WorkingDirectory = $project
$shortcut.IconLocation = $icon
$shortcut.Description = 'Open the local AUTOCLIP AI clip editor'
$shortcut.Save()
Write-Host "Desktop shortcut created: $destination"
