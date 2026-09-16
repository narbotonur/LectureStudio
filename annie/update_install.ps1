param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$StagedDir,
    [Parameter(Mandatory=$true)][int]$WaitPid
)
$ErrorActionPreference = 'Stop'
$backup = $null
$movedOld = $false
$movedNew = $false
try {
    $install = (Resolve-Path -LiteralPath $InstallDir).Path
    $staged = (Resolve-Path -LiteralPath $StagedDir).Path
    $parent = Split-Path -Parent $install
    $stageParent = Split-Path -Parent $staged
    if ((Split-Path -Leaf $install) -ne 'LectureStudio' -or
        (Split-Path -Leaf $staged) -ne 'LectureStudio' -or
        (Split-Path -Parent $stageParent) -ne $parent -or
        (Split-Path -Leaf $stageParent) -notlike 'LectureStudio-update-*' -or $install -eq $staged) {
        throw 'Invalid installation paths. Nothing was replaced.'
    }
    foreach ($directory in @($install, $stageParent, $staged)) {
        if ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Linked installation directories require manual installation.'
        }
    }
    foreach ($directory in @($install, $staged)) {
        foreach ($name in @('LectureStudio.exe','LectureStudioWorker.exe','_internal')) {
            if (-not (Test-Path -LiteralPath (Join-Path $directory $name))) { throw 'Incomplete app bundle.' }
        }
    }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        $owner = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
        $busy = @(Get-Process -Name 'LectureStudio*' -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and $_.Path.StartsWith($install + '\', [StringComparison]::OrdinalIgnoreCase)
        })
        if (-not $owner -and $busy.Count -eq 0) { break }
        if ((Get-Date) -gt $deadline) { throw 'Studio is still running. Quit Studio and its watcher, then retry the update.' }
        Start-Sleep -Milliseconds 500
    } while ($true)
    $backup = Join-Path $parent ('LectureStudio.backup-' + [Guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $install -Destination $backup
    $movedOld = $true
    Move-Item -LiteralPath $staged -Destination $install
    $movedNew = $true
    # This is the visible GUI the user explicitly chose to restart.
    Start-Process -FilePath (Join-Path $install 'LectureStudio.exe') -WorkingDirectory $install -WindowStyle Normal
} catch {
    $message = $_.Exception.Message
    try {
        if ($movedNew) { Move-Item -LiteralPath $install -Destination $staged }
        if ($movedOld) { Move-Item -LiteralPath $backup -Destination $install }
    } catch { $message += "`nRecovery needed. Your previous app is at: $backup" }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, 'Lecture Studio update') | Out-Null
    exit 1
}
