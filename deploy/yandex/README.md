# Сайт в Yandex Cloud, вычисления на компьютере лаборатории

```
 Пользователи ──HTTPS──▶ Сервер Yandex Cloud (10.8.0.1)          Компьютер лаборатории (10.8.0.2)
                        nginx · frontend · backend      ◀──────▶  runner-cpu · MLflow
                        Postgres · Redis (очередь)      WireGuard  KBRAG · Qwen · импорт статей
                        /opt/esg_data  ◀──── Syncthing ────▶  C:\Users\…\ESG_data
```

- **Сервер** работает круглосуточно: сайт, пользователи, база платформы и очередь запусков.
- **Компьютер** забирает задачи из очереди через туннель и считает. Если он выключен, сайт работает,
  а запуски, Qwen и импорт статей ждут в очереди.
- **Папка данных** синхронизируется в обе стороны: датасеты, загруженные на сайт, приезжают на
  компьютер, а результаты запусков уезжают на сервер.

---

## 1. Сервер

Консоль Yandex Cloud → Compute Cloud → **Создать ВМ**:

| Параметр | Значение |
|---|---|
| Образ | Ubuntu 24.04 LTS |
| Зона | ru-central1-a |
| Платформа | Intel Ice Lake |
| vCPU / доля / RAM | **2 vCPU, 50 %, 4 ГБ** |
| Диск | SSD, **20 ГБ + размер вашей папки ESG_data** |
| Публичный IP | **статический** (VPC → IP-адреса → Зарезервировать) |
| Доступ | логин `esg` и ваш публичный SSH-ключ |

Размер папки: на компьютере правой кнопкой по `ESG_data` → «Свойства».

**Группа безопасности** (VPC → Группы безопасности), входящие правила:

| Порт | Протокол | Источник |
|---|---|---|
| 22 | TCP | ваш IP |
| 80, 443 | TCP | 0.0.0.0/0 |
| 51820 | UDP | 0.0.0.0/0 |

**Домен.** Создайте A-запись `esg.ваш-домен.ru` → IP сервера. Если домена нет, используйте
`<IP>.sslip.io`, например `51.250.1.2.sslip.io`: он сам указывает на этот IP.

## 2. Установка на сервере

```bash
ssh esg@<IP>
curl -fsSL https://raw.githubusercontent.com/Shlopa-alt/ESG_XAI/main/deploy/yandex/setup.sh -o setup.sh
sudo DOMAIN=esg.ваш-домен.ru EMAIL=you@example.ru PC_DATA_DIR=C:/Users/Grisha/ESG_data bash setup.sh
```

`PC_DATA_DIR` — папка данных на компьютере, то же значение, что `ESG_DATA_HOST` в его `deploy/.env`.

В конце скрипт печатает:

- адрес сайта;
- логин `admin` и временный пароль;
- ID Syncthing сервера;
- пути к двум файлам для компьютера.

Скачайте эти файлы к себе (команда выполняется **на компьютере**):

```powershell
scp esg@<IP>:esg-pc/* .
```

## 3. Компьютер лаборатории (Windows)

1. **Остановите локальный сайт.** Если хотите перенести данные, сначала сделайте шаг 4.
   ```powershell
   docker compose -f deploy\docker-compose.yml down
   ```
2. **Туннель.**
   - Установите WireGuard: https://www.wireguard.com/install/.
   - «Импорт туннеля из файла» → `esg-tunnel.conf` → «Подключить».
   - Проверьте связь: `ping 10.8.0.1`.
3. **Сеть для KBRAG.** В PowerShell **от администратора**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\yandex\pc_network.ps1
   ```
4. **Настройки.** Добавьте строки из `pc-env.txt` в `deploy\.env`, заменив совпадающие.
5. **Синхронизация папки данных.**
   - Установите Syncthing для Windows: https://github.com/Bill-Stewart/SyncthingWindowsSetup/releases.
   - Откройте http://127.0.0.1:8384, затем «Действия → Показать ID» и скопируйте ID.
   - На сервере выполните:
     ```bash
     sudo /opt/ESG_XAI/deploy/yandex/link-pc.sh <ID компьютера>
     ```
   - В Syncthing на компьютере: «Добавить удалённое устройство», ID сервера, на вкладке
     «Дополнительно» адрес `tcp://10.8.0.1:22000`.
   - Примите предложенную папку «ESG data» и укажите **вашу существующую** папку `C:\Users\…\ESG_data`.
   - Дождитесь статуса «Синхронизировано».
6. **Токен KBRAG.** Создайте токен на компьютере:
   ```powershell
   python kbrag.py access add platform --kb esg
   ```
   Затем впишите его на сервере в `/opt/ESG_XAI/deploy/.env` (строка `KBRAG_TOKEN=`) и выполните:
   ```bash
   cd /opt/ESG_XAI/deploy && sudo docker compose -f docker-compose.yml -f yandex/docker-compose.yandex.yml up -d
   ```
7. **Запуск вычислений.**
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\start_all.ps1
   ```
   Видя `PLATFORM_URL` в `.env`, скрипт поднимает только исполнитель и MLflow, а KBRAG, обработчики
   импорта и Qwen направляет на сервер. Если автозапуск уже ставили через `install.ps1`, дальше всё
   будет подниматься само после входа в Windows.

## 4. Перенос данных с локального сайта (если он уже работал)

На компьютере, пока локальный сайт ещё запущен:

```powershell
docker compose -f deploy\docker-compose.yml exec postgres pg_dump -U esg -Fc -f /tmp/esg.dump esg
docker compose -f deploy\docker-compose.yml cp postgres:/tmp/esg.dump esg.dump
scp esg.dump esg@<IP>:~
```

На сервере:

```bash
cd /opt/ESG_XAI/deploy
C="sudo docker compose -f docker-compose.yml -f yandex/docker-compose.yandex.yml"
$C cp ~/esg.dump postgres:/tmp/esg.dump
$C exec postgres pg_restore -U esg -d esg --clean --if-exists /tmp/esg.dump
$C restart backend
$C exec backend python -m app.manage set-password <ваш логин> --role owner   # пароль для входа
```

Пути датасетов и запусков в базе — пути компьютера (`C:/Users/…`), сервер понимает их без правок.

## 5. Проверка

- **Сайт.** Откройте `https://ваш-домен`, войдите и смените временный пароль.
- **Запуски.** Запустите эксперимент из формы: ход должен идти в реальном времени.
- **Исполнитель.** Если запуски не стартуют, посмотрите журнал на компьютере:
  ```powershell
  docker compose -f deploy\yandex\docker-compose.pc.yml --env-file deploy\.env logs runner-cpu
  ```
- **База знаний.** Откройте страницу базы знаний. Если она отвечает ошибкой, проверьте туннель
  (`ping 10.8.0.2` с сервера), `KBRAG_TOKEN` и что веб-сервер KBRAG запущен.

## Обслуживание

```bash
sudo bash /opt/ESG_XAI/deploy/yandex/setup.sh                 # обновить сайт: git pull + пересборка
cd /opt/ESG_XAI/deploy && C="sudo docker compose -f docker-compose.yml -f yandex/docker-compose.yandex.yml"
$C ps;  $C logs -f backend                                      # состояние и журнал
$C exec postgres pg_dump -U esg esg | gzip > ~/esg-$(date +%F).sql.gz   # копия базы
sudo wg show                                                    # туннель: время последнего контакта
```

Резервные копии удобнее всего делать **расписанием снимков диска** ВМ: Compute Cloud → Снимки
дисков → Расписания.

**Обратите внимание:**

- **Загрузка датасета.** После загрузки датасета на сайт подождите несколько секунд, пока файл
  доедет до компьютера, и только потом запускайте эксперимент. Иначе исполнитель не найдёт срез.
- **Данные под NDA.** Они теперь лежат и на облачном сервере. Если это недопустимо, ограничьте
  доступ к сайту адресами центра (`ALLOWED_SUBNET` в `.env` или правила 80/443 в группе
  безопасности) и согласуйте размещение с ответственными.
