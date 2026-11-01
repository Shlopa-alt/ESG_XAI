#!/usr/bin/env bash
# Сервер ESG Open Research в Yandex Cloud: только сайт; вычисления — на компьютере лаборатории.
# Чистая ВМ Ubuntu 22.04/24.04:
#
#   curl -fsSL https://raw.githubusercontent.com/Shlopa-alt/ESG_XAI/main/deploy/yandex/setup.sh -o setup.sh
#   sudo DOMAIN=esg.example.ru EMAIL=you@example.ru PC_DATA_DIR=C:/Users/Grisha/ESG_data bash setup.sh
#
# PC_DATA_DIR — папка данных на компьютере (как ESG_DATA_HOST в его deploy/.env).
# DOMAIN обязателен (A-запись на IP сервера); своего домена нет — DOMAIN=<IP>.sslip.io.
# Повторный запуск безопасен: обновляет код и пересобирает контейнеры, ключи и пароли не трогает.
# Файлы для компьютера (настройка туннеля и строки для deploy/.env) — в /root/esg-pc/.
set -euo pipefail

DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
PC_DATA_DIR="${PC_DATA_DIR:-}"
OWNER_LOGIN="${OWNER_LOGIN:-admin}"
REPO_URL="${REPO_URL:-https://github.com/Shlopa-alt/ESG_XAI.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/opt/ESG_XAI}"
DATA_DIR=/opt/esg_data
OUT=/root/esg-pc
WG_PORT=51820

[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
# Исполнитель на компьютере проверяет сертификат сайта — нужен домен и сертификат Let's Encrypt.
# Своего домена нет — подойдёт <публичный IP>.sslip.io (например 51.250.1.2.sslip.io)
[[ -n "$DOMAIN" && -n "$EMAIL" ]] || { echo "Укажите DOMAIN и EMAIL (без домена: DOMAIN=<IP>.sslip.io)"; exit 1; }

log() { printf '\n==> %s\n' "$*"; }
rnd() { openssl rand -hex 32; }

log "Пакеты: Docker, WireGuard, Syncthing, certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io git openssl certbot curl wireguard syncthing
apt-get install -y -q docker-compose-v2 || apt-get install -y -q docker-compose-plugin

# Docker Hub из российских облаков бывает недоступен — зеркало Google как запасной путь
if [[ ! -f /etc/docker/daemon.json ]]; then
  echo '{ "registry-mirrors": ["https://mirror.gcr.io"] }' > /etc/docker/daemon.json
fi

# Сборка фронтенда на 2–4 ГБ памяти без подкачки может упасть
if [[ ! -f /swapfile ]]; then
  log "Файл подкачки 2 ГБ"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

PUBLIC_IP=$(curl -fs -H Metadata-Flavor:Google \
  http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip \
  || curl -fs https://ifconfig.me)
SITE="${DOMAIN:-$PUBLIC_IP}"
mkdir -p "$OUT" && chmod 700 "$OUT"

# --- Туннель WireGuard: сервер 10.8.0.1, компьютер 10.8.0.2 -------------------------------------
if [[ ! -f /etc/wireguard/wg0.conf ]]; then
  log "Туннель WireGuard"
  umask 077
  SRV_KEY=$(wg genkey); SRV_PUB=$(echo "$SRV_KEY" | wg pubkey)
  PC_KEY=$(wg genkey);  PC_PUB=$(echo "$PC_KEY" | wg pubkey)
  cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = 10.8.0.1/24
ListenPort = $WG_PORT
PrivateKey = $SRV_KEY

[Peer]
# компьютер лаборатории
PublicKey = $PC_PUB
AllowedIPs = 10.8.0.2/32
EOF
  cat > "$OUT/esg-tunnel.conf" <<EOF
[Interface]
PrivateKey = $PC_KEY
Address = 10.8.0.2/24

[Peer]
PublicKey = $SRV_PUB
Endpoint = $PUBLIC_IP:$WG_PORT
AllowedIPs = 10.8.0.1/32
PersistentKeepalive = 25
EOF
  umask 022
fi
systemctl enable --now wg-quick@wg0
# Redis слушает адрес туннеля — Docker должен стартовать после него
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/after-wireguard.conf <<'EOF'
[Unit]
Wants=wg-quick@wg0.service
After=wg-quick@wg0.service
EOF
systemctl daemon-reload
systemctl enable docker
systemctl restart docker

# --- Код -----------------------------------------------------------------------------------------
log "Код: $REPO_DIR"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi
DEPLOY="$REPO_DIR/deploy"
COMPOSE=(docker compose -f "$DEPLOY/docker-compose.yml" -f "$DEPLOY/yandex/docker-compose.yandex.yml")
chmod +x "$DEPLOY/yandex/"*.sh
mkdir -p "$DATA_DIR/kb_inbox" /var/www/acme "$DEPLOY/certs"

# --- Настройки -----------------------------------------------------------------------------------
if [[ ! -f "$DEPLOY/.env" ]]; then
  [[ -n "$PC_DATA_DIR" ]] || { echo "Укажите PC_DATA_DIR — папку данных на компьютере, например C:/Users/Grisha/ESG_data"; exit 1; }
  PC_DATA_DIR="${PC_DATA_DIR//\\//}"; PC_DATA_DIR="${PC_DATA_DIR%/}"
  log "Настройки: $DEPLOY/.env (секреты сгенерированы)"
  cat > "$DEPLOY/.env" <<EOF
POSTGRES_PASSWORD=$(rnd)
SECRET_KEY=$(rnd)
HTTP_PORT=443
COOKIE_SECURE=true
ALLOWED_SUBNET=0.0.0.0/0

# password — личные пароли; пользователей заводит владелец на странице «Пользователи»
AUTH_BACKEND=password
LOCAL_DEV_PASSWORD=$(rnd)
INITIAL_OWNER_LOGINS=[]

# Очередь запусков (Redis) — исполнитель на компьютере подключается через туннель
REDIS_PASSWORD=$(rnd)

# KBRAG на компьютере, через туннель (проброс порта 8001 — deploy/yandex/pc_network.ps1)
KBRAG_URL=http://10.8.0.2:8001
# Токен платформы в KBRAG: python kbrag.py access add platform --kb esg (на компьютере)
KBRAG_TOKEN=

# Данные: на сервере лежат в $DATA_DIR (синхронизируется с компьютером),
# а пути в платформе — пути компьютера, их читает исполнитель
SERVER_DATA_DIR=$DATA_DIR
ESG_DATA_HOST=$PC_DATA_DIR
KB_INBOX_DIR=$DATA_DIR/kb_inbox
KB_IMPORT_MAX_MB=60

# Общие секреты с обработчиками на компьютере
RUNNER_TOKEN=$(rnd)
KB_IMPORT_TOKEN=$(rnd)
QWEN_TOKEN=$(rnd)
EOF
  chmod 600 "$DEPLOY/.env"
fi
envget() { grep -m1 "^$1=" "$DEPLOY/.env" | cut -d= -f2-; }

cat > "$OUT/pc-env.txt" <<EOF
# Добавьте в deploy/.env на компьютере (значения, которые там уже есть, замените этими)
PLATFORM_URL=https://$SITE
REDIS_PASSWORD=$(envget REDIS_PASSWORD)
RUNNER_TOKEN=$(envget RUNNER_TOKEN)
KB_IMPORT_TOKEN=$(envget KB_IMPORT_TOKEN)
QWEN_TOKEN=$(envget QWEN_TOKEN)
ESG_DATA_HOST=$(envget ESG_DATA_HOST)
KB_INBOX_DIR=$(envget ESG_DATA_HOST)/kb_inbox
EOF
chmod 600 "$OUT/pc-env.txt"

# --- Синхронизация папки данных (Syncthing) -------------------------------------------------------
log "Syncthing"
systemctl enable --now syncthing@root
for _ in $(seq 1 30); do syncthing cli show system >/dev/null 2>&1 && break; sleep 2; done
if ! syncthing cli config folders list 2>/dev/null | grep -qx esg-data; then
  syncthing cli config folders add --id esg-data --label "ESG data" --path "$DATA_DIR"
fi

# --- Сертификат ----------------------------------------------------------------------------------
if [[ ! -f "$DEPLOY/certs/server.crt" ]]; then
  log "Временный самоподписанный сертификат"
  SAN="IP:$PUBLIC_IP"; [[ -n "$DOMAIN" ]] && SAN="DNS:$DOMAIN,$SAN"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$DEPLOY/certs/server.key" -out "$DEPLOY/certs/server.crt" \
    -subj "/CN=$SITE" -addext "subjectAltName=$SAN" 2>/dev/null
fi

log "Сборка и запуск контейнеров (первый раз — 5–15 минут)"
"${COMPOSE[@]}" up -d --build --remove-orphans

if [[ -n "$DOMAIN" && ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  log "Сертификат Let's Encrypt для $DOMAIN"
  sleep 5
  certbot certonly --webroot -w /var/www/acme -d "$DOMAIN" \
    --email "$EMAIL" --agree-tos -n \
    --deploy-hook "$DEPLOY/yandex/install-cert.sh"
  "$DEPLOY/yandex/install-cert.sh" "/etc/letsencrypt/live/$DOMAIN"
fi

if [[ ! -f "$OUT/owner.txt" ]]; then
  log "Первый владелец: $OWNER_LOGIN"
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T backend python -m app.manage set-password "$OWNER_LOGIN" --role owner \
         > "$OUT/owner.txt" 2>/dev/null; then
      chmod 600 "$OUT/owner.txt"; break
    fi
    rm -f "$OUT/owner.txt"; sleep 5
  done
fi

# Копия файлов для компьютера в домашнюю папку пользователя, чтобы забрать их через scp
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
  USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
  mkdir -p "$USER_HOME/esg-pc"
  cp "$OUT/esg-tunnel.conf" "$OUT/pc-env.txt" "$USER_HOME/esg-pc/"
  chown -R "$SUDO_USER:" "$USER_HOME/esg-pc" && chmod 700 "$USER_HOME/esg-pc"
fi

SRV_ID=$(syncthing cli show system | grep -oP '"myID":\s*"\K[^"]+')
log "Готово"
"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
cat <<EOF

Сайт:              https://$SITE
Вход владельца:    $(cat "$OUT/owner.txt" 2>/dev/null || echo 'не создан — см. журнал backend')
ID Syncthing:      $SRV_ID
Для компьютера:    ~/esg-pc/esg-tunnel.conf   (туннель WireGuard)
                   ~/esg-pc/pc-env.txt        (строки для deploy/.env)
                   забрать на компьютер:  scp ${SUDO_USER:-root}@$PUBLIC_IP:esg-pc/* .
Дальше:            после установки Syncthing на компьютере —
                   sudo $DEPLOY/yandex/link-pc.sh <ID Syncthing компьютера>
EOF
