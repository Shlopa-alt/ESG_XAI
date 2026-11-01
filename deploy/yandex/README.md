# Хостинг в Yandex Cloud

Вся платформа (Postgres, Redis, MLflow, backend, runner-cpu, frontend, nginx) работает на одной
виртуальной машине Compute Cloud в Docker Compose — так же, как локально.

## 1. Виртуальная машина

Консоль Yandex Cloud → **Compute Cloud → Создать ВМ**:

| Параметр | Значение |
|---|---|
| Образ | Ubuntu 24.04 LTS |
| Зона | ru-central1-a (любая) |
| Платформа | Intel Ice Lake (standard-v3) |
| vCPU / RAM | **4 vCPU, 8 ГБ** (минимум 2 / 4 — сборка исполнителя с torch на меньшем падает) |
| Гарантированная доля vCPU | 100 % (на 20–50 % расчёты runner-cpu идут очень медленно) |
| Диск | SSD, **50 ГБ** |
| Сеть | публичный IP — **статический** (VPC → IP-адреса → зарезервировать) |
| Доступ | логин, например `esg`, и ваш публичный SSH-ключ |

**Группа безопасности** (VPC → Группы безопасности) — входящие правила:
TCP 22 (лучше только ваш IP), TCP 80 и TCP 443 с `0.0.0.0/0`. Исходящие — всё разрешено.

То же из CLI `yc`:

```bash
yc vpc address create --name esg-ip --external-ipv4 zone=ru-central1-a
yc compute instance create --name esg --zone ru-central1-a --platform standard-v3 \
  --cores 4 --memory 8 --core-fraction 100 \
  --create-boot-disk image-folder-id=standard-images,image-family=ubuntu-2404-lts,size=50,type=network-ssd \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4,nat-address=<IP из первой команды> \
  --ssh-key ~/.ssh/id_ed25519.pub
```

## 2. Домен (рекомендуется)

Создайте A-запись `esg.ваш-домен.ru → <статический IP>` (у регистратора или в Cloud DNS).
С доменом сайт получает настоящий сертификат Let's Encrypt, продление — автоматически.
Без домена сайт работает по `https://<IP>` с самоподписанным сертификатом (предупреждение в браузере).

## 3. Установка

```bash
ssh esg@<IP>
curl -fsSL https://raw.githubusercontent.com/Shlopa-alt/ESG_XAI/main/deploy/yandex/setup.sh -o setup.sh
sudo DOMAIN=esg.ваш-домен.ru EMAIL=you@example.ru OWNER_LOGIN=admin bash setup.sh
```

Скрипт ставит Docker, клонирует репозиторий в `/opt/ESG_XAI`, генерирует `deploy/.env` со случайными
секретами, собирает и запускает контейнеры (первый раз 10–20 минут), получает сертификат и заводит
владельца. В конце печатает адрес и **временный пароль** владельца — его меняют при первом входе.
Остальных пользователей владелец заводит на странице «Пользователи».

Если репозиторий приватный, склонируйте его в `/opt/ESG_XAI` вручную (deploy-ключ или токен) до запуска
скрипта — дальше он только делает `git pull`.

## 4. Обновление

```bash
sudo bash /opt/ESG_XAI/deploy/yandex/setup.sh       # git pull + пересборка, .env и пароли не меняются
```

## Что работает и что нет

- **Режим входа** — `AUTH_BACKEND=password` (личные пароли). LDAP университета из облака обычно недоступен;
  если доступен — поменяйте `AUTH_BACKEND=ldap` и `LDAP_*` в `/opt/ESG_XAI/deploy/.env` и перезапустите.
- **База знаний KBRAG** и **Qwen** живут на отдельных машинах лаборатории. Без них страницы базы знаний
  и функции Qwen отвечают ошибкой, остальное работает. Чтобы подключить KBRAG, укажите в `.env`
  `KBRAG_URL` (адрес, доступный из облака) и `KBRAG_TOKEN`.
- **Данные и результаты запусков** — `/opt/esg_data` на ВМ.
- **Доступ только из сети центра**: задайте `ALLOWED_SUBNET` (CIDR) в `.env` или ограничьте 80/443
  в группе безопасности.

## Полезные команды

```bash
cd /opt/ESG_XAI/deploy
C="docker compose -f docker-compose.yml -f yandex/docker-compose.yandex.yml"
$C ps                                   # состояние
$C logs -f backend                      # журнал
$C restart backend                      # после правки .env: $C up -d
$C exec backend python -m app.manage set-password <логин> --role owner   # сброс пароля
$C exec postgres pg_dump -U esg esg | gzip > ~/esg-$(date +%F).sql.gz   # резервная копия БД
```

Для резервного копирования проще всего настроить в консоли расписание **снимков диска** ВМ
(Compute Cloud → Снимки дисков → Расписания).
