# Creates the Desktop shortcut that starts scripts\desktop_app.ps1 without a
# console window. Keep this file ASCII-only (see desktop_app.ps1).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "desktop_app.ps1"
$icon = Join-Path $Root "resource\desktop_app.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "MoneyPrinterTurbo.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = $Root
$shortcut.Description = "MoneyPrinterTurbo"
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = $icon }
$shortcut.Save()
Write-Output "Shortcut created: $shortcutPath"
