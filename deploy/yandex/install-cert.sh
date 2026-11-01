#!/usr/bin/env bash
# Копирует сертификат Let's Encrypt в deploy/certs и перезагружает nginx.
# Вызывается certbot'ом после каждого продления (--deploy-hook, переменная RENEWED_LINEAGE)
# или вручную: install-cert.sh /etc/letsencrypt/live/<домен>
set -euo pipefail

LINEAGE="${1:-${RENEWED_LINEAGE:?укажите папку /etc/letsencrypt/live/<домен>}}"
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"

install -m 644 "$LINEAGE/fullchain.pem" "$DEPLOY_DIR/certs/server.crt"
install -m 600 "$LINEAGE/privkey.pem" "$DEPLOY_DIR/certs/server.key"

docker compose -f "$DEPLOY_DIR/docker-compose.yml" -f "$DEPLOY_DIR/yandex/docker-compose.yandex.yml" \
  exec -T nginx nginx -s reload
echo "Сертификат обновлён: $LINEAGE"
