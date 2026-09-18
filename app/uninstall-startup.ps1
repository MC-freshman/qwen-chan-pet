$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'qwen-chan-pet.lnk'
if (Test-Path $link) { Remove-Item $link; Write-Host "已移除开机自启: $link" } else { Write-Host "没有注册过开机自启" }

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*qwen*' -and ($_.CommandLine -like '*sentinel.pyw*' -or $_.CommandLine -like '*pet.pyw*') } |
  ForEach-Object { Write-Host "结束 $($_.CommandLine)"; Stop-Process -Id $_.ProcessId -Force }
