# Creates (or removes) the "FKey Automator" shortcuts on the Desktop and in the Start menu.
param(
    [string]$Target = "",
    [string]$Script = "",
    [string]$WorkDir = "",
    [string]$Icon = "",
    [switch]$UseLauncher,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$name = "FKey Automator"
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs")
)

if ($Remove) {
    foreach ($dir in $places) {
        $lnk = Join-Path $dir "$name.lnk"
        if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
    }
    exit 0
}

if (-not $Target -or -not $Script) {
    Write-Error "Target and Script are required."
    exit 1
}

$arguments = '"' + $Script + '"'
if ($UseLauncher) { $arguments = '-3 ' + $arguments }

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $places) {
    $lnk = Join-Path $dir "$name.lnk"
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $Target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $WorkDir
    if ($Icon) { $s.IconLocation = $Icon }
    $s.Description = "FKey Automator"
    $s.Save()
}
