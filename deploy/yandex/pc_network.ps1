# Однократно, от администратора: сервер (10.8.0.1, через туннель WireGuard) получает доступ к KBRAG
# этой машины и к Syncthing. Веб-сервер KBRAG слушает 127.0.0.1:8000 — проброс 8001 -> 8000.
#   powershell -ExecutionPolicy Bypass -File deploy\yandex\pc_network.ps1
# Отменить:  netsh interface portproxy delete v4tov4 listenport=8001 listenaddress=0.0.0.0
#            Remove-NetFirewallRule -DisplayName "ESG: *"

$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Запустите PowerShell от имени администратора"; exit 1 }

netsh interface portproxy delete v4tov4 listenport=8001 listenaddress=0.0.0.0 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenport=8001 listenaddress=0.0.0.0 connectport=8000 connectaddress=127.0.0.1
Set-Service iphlpsvc -StartupType Automatic
Start-Service iphlpsvc

Get-NetFirewallRule -DisplayName "ESG: *" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "ESG: KBRAG для сервера" -Direction Inbound -Protocol TCP -LocalPort 8001 `
    -RemoteAddress 10.8.0.1 -Action Allow -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "ESG: Syncthing с сервера" -Direction Inbound -Protocol TCP -LocalPort 22000 `
    -RemoteAddress 10.8.0.1 -Action Allow -Profile Any | Out-Null

Write-Host "Готово: KBRAG доступен серверу по http://10.8.0.2:8001, порт Syncthing открыт для сервера."
Write-Host "Проверка туннеля: ping 10.8.0.1"
