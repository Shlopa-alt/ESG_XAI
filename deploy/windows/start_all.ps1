# Автозапуск после входа в Windows: ждёт Docker, поднимает платформу и базу KBRAG,
# запускает веб-сервер KBRAG (поиск и граф для платформы) и обработчик импорта статей с сайта. Журнал — logs\start_all.log рядом.
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

# Сайт на сервере (PLATFORM_URL в deploy\.env) — здесь только исполнитель и MLflow;
# иначе — вся платформа на этой машине
$EnvFile = Join-Path $Platform "deploy\.env"
$Remote = (Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern '^\s*PLATFORM_URL\s*=\s*\S' -Quiet)
if ($Remote) {
    & $Docker compose -f (Join-Path $Platform "deploy\yandex\docker-compose.pc.yml") --env-file $EnvFile up -d *>> $Log
    Say "сайт на сервере: подняты исполнитель и MLflow"
} else {
    & $Docker compose -f (Join-Path $Platform "deploy\docker-compose.yml") up -d *>> $Log
}
if ($Remote) {
    # Синхронизация папки данных с сервером (Syncthing; ставится winget install Syncthing.Syncthing)
    $st = Get-Command syncthing -ErrorAction SilentlyContinue
    if (-not $st) {
        $st = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter syncthing.exe `
            -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    $stPath = if ($st.Source) { $st.Source } else { $st.FullName }
    if (-not $stPath) {
        Say "Syncthing не установлен — папка данных не синхронизируется с сервером"
    } elseif (-not (Get-Process syncthing -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $stPath -ArgumentList "serve", "--no-browser", "--no-restart" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\syncthing.log") `
            -RedirectStandardError (Join-Path $PSScriptRoot "logs\syncthing.err.log")
        Say "Syncthing запущен"
    } else {
        Say "Syncthing уже работает"
    }
}
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

# Обработчик импорта статей, загруженных через сайт (kb_import_worker.py): разбор на процессоре
$worker = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*kb_import_worker.py*" }
if (-not $worker) {
    $env:KBRAG_DSN = "postgresql://kbrag:kbrag@127.0.0.1:5434/kbrag"
    $env:KBRAG_HOME = $Kbrag
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process -FilePath (Join-Path $Kbrag ".venv\Scripts\python.exe") `
        -ArgumentList (Join-Path $PSScriptRoot "kb_import_worker.py") `
        -WorkingDirectory $Kbrag -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\kb_import.log") `
        -RedirectStandardError (Join-Path $PSScriptRoot "logs\kb_import.err.log")
    Say "обработчик импорта статей запущен"
} else {
    Say "обработчик импорта статей уже работает"
}

# Обработчик задач Qwen: поднимает модель, когда в очереди есть работа, и выключает после простоя
$qwen = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*qwen*worker.py*" }
if (-not $qwen) {
    $env:KBRAG_HOME = $Kbrag
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process -FilePath "py" -ArgumentList "-3.12", (Join-Path $Platform "runner\qwen\worker.py") `
        -WorkingDirectory $Platform -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\qwen_worker.log") `
        -RedirectStandardError (Join-Path $PSScriptRoot "logs\qwen_worker.err.log")
    Say "обработчик Qwen запущен"
} else {
    Say "обработчик Qwen уже работает"
}
