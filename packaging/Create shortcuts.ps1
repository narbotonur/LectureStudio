$ErrorActionPreference = 'Stop'
$packagePath = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$executablePath = Join-Path $packagePath 'LectureStudio.exe'
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) { throw 'Extract the full ZIP before creating shortcuts.' }
$shortcutShell = New-Object -ComObject WScript.Shell
foreach ($destination in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $shortcut = $shortcutShell.CreateShortcut((Join-Path $destination 'Lecture Studio.lnk'))
    $shortcut.TargetPath = $executablePath
    $shortcut.WorkingDirectory = $packagePath
    $shortcut.Description = 'Annie Lecture Studio'
    $shortcut.Save()
}
Write-Output 'Created Lecture Studio desktop and Start-menu shortcuts. Startup monitoring remains opt-in inside the app.'
