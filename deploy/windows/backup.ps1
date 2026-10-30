# Ночной бэкап: дампы баз платформы и KBRAG, настройки KBRAG и срезы данных.
# Кладёт в $Target\<дата>\, хранит 14 последних дней. Журнал — logs\backup.log рядом.
#
#   powershell -File deploy\windows\backup.ps1 [-Target D:\ESG_backups]
#
# Восстановление базы платформы:
#   docker compose -f deploy\docker-compose.yml exec -T postgres psql -U esg -d esg < esg.sql
# KBRAG:
#   docker exec -i kbrag-db psql -U kbrag -d kbrag < kbrag.sql

param([string]$Target = "C:\Users\Grisha\ESG_backups", [int]$Keep = 14)

$ErrorActionPreference = "Continue"
$Platform = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Kbrag = if ($env:KBRAG_HOME) { $env:KBRAG_HOME } else { "C:\Users\Grisha\KBRAG" }
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$Log = Join-Path $PSScriptRoot "logs\backup.log"
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
function Say($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File $Log -Append -Encoding utf8 }

$day = Join-Path $Target (Get-Date -Format "yyyy-MM-dd")
New-Item -ItemType Directory -Force $day | Out-Null
$ok = $true

# pg_dump пишем внутри контейнера и копируем файл: без перекодировки потока PowerShell
& $Docker compose -f (Join-Path $Platform "deploy\docker-compose.yml") exec -T postgres `
    sh -c "pg_dump -U esg -d esg --clean --if-exists > /tmp/esg.sql"
& $Docker compose -f (Join-Path $Platform "deploy\docker-compose.yml") cp postgres:/tmp/esg.sql (Join-Path $day "esg.sql")
if (-not (Test-Path (Join-Path $day "esg.sql"))) { $ok = $false; Say "ОШИБКА: дамп платформы" }

& $Docker exec kbrag-db sh -c "pg_dump -U kbrag -d kbrag --clean --if-exists > /tmp/kbrag.sql"
& $Docker cp kbrag-db:/tmp/kbrag.sql (Join-Path $day "kbrag.sql")
if (-not (Test-Path (Join-Path $day "kbrag.sql"))) { $ok = $false; Say "ОШИБКА: дамп KBRAG" }

# Настройки и доступы KBRAG (в git не идут), срезы данных экспериментов
Copy-Item (Join-Path $Kbrag "config\kbs") (Join-Path $day "kbrag-config-kbs") -Recurse -Force
Copy-Item (Join-Path $Kbrag ".local\access.yaml") $day -Force -ErrorAction SilentlyContinue
# Срезы данных и результаты расчётов — зеркало (только изменения; занятые файлы не мешают)
if (Test-Path "C:\Users\Grisha\ESG_data") {
    robocopy "C:\Users\Grisha\ESG_data" (Join-Path $Target "ESG_data") /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { $ok = $false; Say "ОШИБКА: копия ESG_data (robocopy $LASTEXITCODE)" }
}

Get-ChildItem $Target -Directory | Where-Object Name -match "^\d{4}-\d{2}-\d{2}$" | Sort-Object Name -Descending | Select-Object -Skip $Keep |
    Remove-Item -Recurse -Force -Confirm:$false
$size = [math]::Round(((Get-ChildItem $day -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Say ("бэкап {0}: {1} МБ{2}" -f $day, $size, $(if ($ok) { "" } else { " — С ОШИБКАМИ" }))
if (-not $ok) { exit 1 }
