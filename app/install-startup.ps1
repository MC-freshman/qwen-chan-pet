$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { Write-Error "PATH 里找不到 pythonw.exe"; exit 1 }
if ($pythonw -like "*WindowsApps*") { Write-Error "解析到的是 Microsoft Store 空壳 pythonw，请先把真 Python 放进 PATH"; exit 1 }

$sentinel = Join-Path $root "sentinel.pyw"
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "qwen-chan-pet.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $sentinel + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = "qwen-chan pet sentinel (follows Qoder)"
$shortcut.Save()

Write-Host "startup shortcut: $link"
Write-Host "target: $pythonw `"$sentinel`""

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*sentinel.pyw*" }
if ($running) {
    Write-Host "sentinel already running: pid $($running.ProcessId)"
} else {
    $proc = Start-Process -FilePath $pythonw -ArgumentList ('"' + $sentinel + '"') -WorkingDirectory $root -PassThru
    Write-Host "sentinel started: pid $($proc.Id)"
}
