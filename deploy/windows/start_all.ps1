# Автозапуск после входа в Windows: ждёт Docker, поднимает платформу и базу KBRAG,
# запускает веб-сервер KBRAG (поиск и граф для платформы). Журнал — logs\start_all.log рядом.
#
# Ставится один раз: deploy\windows\install.ps1 (ярлык в автозагрузке и ночной бэкап).
# Пути — переменные ниже; KBRAG_DSN — порт базы KBRAG на этой машине.

$ErrorActionPreference = "Continue"
$Platform = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)          # ...\ESG_XAI
$Kbrag = if ($env:KBRAG_HOME) { $env:KBRAG_HOME } else { "C:\Users\Grisha\KBRAG" }
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$Log = Join-Path $PSScriptRoot "logs\start_all.log"
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
function Say($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File $Log -Append -Encoding utf8 }

Say "старт"
for ($i = 0; $i -lt 60; $i++) {                       # до 10 минут ждём Docker Desktop
    & $Docker info *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep 10
}
if ($LASTEXITCODE -ne 0) { Say "Docker так и не ответил — выхожу"; exit 1 }
Say "Docker готов"

& $Docker compose -f (Join-Path $Platform "deploy\docker-compose.yml") up -d *>> $Log
Push-Location $Kbrag
& $Docker compose up -d db *>> $Log                    # только база; модель — по команде
Pop-Location
Say "контейнеры подняты"

# Веб-сервер KBRAG: векторы на процессоре, чтобы видеокарта оставалась модели графа
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*kbrag.web.server*" }
if (-not $running) {
    $env:KBRAG_DSN = "postgresql://kbrag:kbrag@127.0.0.1:5434/kbrag"
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process -FilePath (Join-Path $Kbrag ".venv\Scripts\python.exe") `
        -ArgumentList "-m", "kbrag.web.server", "--no-browser", "--kb", "esg", "--device", "cpu" `
        -WorkingDirectory $Kbrag -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Kbrag ".local\logs\web.log") `
        -RedirectStandardError (Join-Path $Kbrag ".local\logs\web.err.log")
    Say "веб-сервер KBRAG запущен"
} else {
    Say "веб-сервер KBRAG уже работает"
}
