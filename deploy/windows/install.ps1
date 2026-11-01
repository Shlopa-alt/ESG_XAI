# Однократная установка эксплуатационных задач для текущего пользователя (без прав администратора):
#  - ярлык в папке «Автозагрузка» на start_all.ps1 — платформа и KBRAG поднимаются после входа;
#  - задача планировщика «ESG Open Research backup» — бэкап каждую ночь в 03:00.
# Удалить: ярлык из shell:startup и  schtasks /Delete /TN "ESG Open Research backup" /F

$start = Join-Path $PSScriptRoot "start_all.ps1"
$backup = Join-Path $PSScriptRoot "backup.ps1"

$startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $startup "ESG Open Research.lnk"))
$lnk.TargetPath = "powershell.exe"
$lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$start`""
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.Save()
"Автозагрузка: $($lnk.FullName)"

schtasks /Create /F /TN "ESG Open Research backup" /SC DAILY /ST 03:00 `
    /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$backup`""
