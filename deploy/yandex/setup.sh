#!/usr/bin/env bash
# Разворачивает ESG Open Research на чистой ВМ Ubuntu 22.04/24.04 в Yandex Cloud.
#
#   curl -fsSL https://raw.githubusercontent.com/Shlopa-alt/ESG_XAI/main/deploy/yandex/setup.sh -o setup.sh
#   sudo DOMAIN=esg.example.ru EMAIL=you@example.ru bash setup.sh
#
# Без DOMAIN сайт работает по IP с самоподписанным сертификатом (браузер покажет предупреждение).
# Повторный запуск безопасен: обновляет код и пересобирает контейнеры, .env и пароли не трогает.
set -euo pipefail

DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
OWNER_LOGIN="${OWNER_LOGIN:-admin}"
REPO_URL="${REPO_URL:-https://github.com/Shlopa-alt/ESG_XAI.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/opt/ESG_XAI}"
DATA_DIR="${DATA_DIR:-/opt/esg_data}"

[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
[[ -z "$DOMAIN" || -n "$EMAIL" ]] || { echo "Для DOMAIN нужен EMAIL (уведомления Let's Encrypt)"; exit 1; }

log() { printf '\n==> %s\n' "$*"; }

log "Пакеты: Docker, git, certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io git openssl certbot curl
apt-get install -y -q docker-compose-v2 || apt-get install -y -q docker-compose-plugin
systemctl enable --now docker

# Docker Hub из российских облаков бывает недоступен — зеркало Google как запасной путь
if [[ ! -f /etc/docker/daemon.json ]]; then
  echo '{ "registry-mirrors": ["https://mirror.gcr.io"] }' > /etc/docker/daemon.json
  systemctl restart docker
fi

# Сборка образа исполнителя (torch, xgboost, shap) на 4–8 ГБ памяти без подкачки может упасть
if [[ ! -f /swapfile ]]; then
  log "Файл подкачки 4 ГБ"
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

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

if [[ ! -f "$DEPLOY/.env" ]]; then
  log "Настройки: $DEPLOY/.env (секреты сгенерированы)"
  rnd() { openssl rand -hex 32; }
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

KBRAG_URL=http://host.docker.internal:8000
KBRAG_TOKEN=
KB_INBOX_DIR=$DATA_DIR/kb_inbox
KB_IMPORT_TOKEN=$(rnd)
KB_IMPORT_MAX_MB=60

ESG_DATA_HOST=$DATA_DIR
RUNNER_TOKEN=$(rnd)
QWEN_TOKEN=$(rnd)
EOF
  chmod 600 "$DEPLOY/.env"
fi

if [[ ! -f "$DEPLOY/certs/server.crt" ]]; then
  log "Временный самоподписанный сертификат"
  IP=$(curl -fs -H Metadata-Flavor:Google \
        http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip \
       || curl -fs https://ifconfig.me || echo 127.0.0.1)
  SAN="IP:$IP"; [[ -n "$DOMAIN" ]] && SAN="DNS:$DOMAIN,$SAN"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$DEPLOY/certs/server.key" -out "$DEPLOY/certs/server.crt" \
    -subj "/CN=${DOMAIN:-$IP}" -addext "subjectAltName=$SAN" 2>/dev/null
fi

log "Сборка и запуск контейнеров (первый раз — 10–20 минут)"
"${COMPOSE[@]}" up -d --build

if [[ -n "$DOMAIN" && ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  log "Сертификат Let's Encrypt для $DOMAIN"
  sleep 5
  certbot certonly --webroot -w /var/www/acme -d "$DOMAIN" \
    --email "$EMAIL" --agree-tos -n \
    --deploy-hook "$DEPLOY/yandex/install-cert.sh"
  "$DEPLOY/yandex/install-cert.sh" "/etc/letsencrypt/live/$DOMAIN"
fi

if [[ ! -f "$DEPLOY/.owner-created" ]]; then
  log "Первый владелец: $OWNER_LOGIN"
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T backend python -m app.manage set-password "$OWNER_LOGIN" --role owner \
         | tee "$DEPLOY/.owner-created"; then
      chmod 600 "$DEPLOY/.owner-created"; break
    fi
    sleep 5
  done
fi

log "Готово"
"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo
echo "Адрес:  https://${DOMAIN:-$(grep -oP 'CN\s*=\s*\K\S+' <(openssl x509 -in "$DEPLOY/certs/server.crt" -noout -subject))}"
echo "Вход:   $(cat "$DEPLOY/.owner-created" 2>/dev/null || echo 'см. журнал backend')"
