#!/usr/bin/env bash
# Связывает Syncthing сервера с компьютером лаборатории и открывает ему папку данных.
#   sudo /opt/ESG_XAI/deploy/yandex/link-pc.sh <ID устройства компьютера>
# ID — в Syncthing на компьютере: «Действия → Показать ID».
# Через REST API: «syncthing cli config devices add --addresses …» в Syncthing 1.27 из Ubuntu
# падает на списке адресов.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
PC_ID="${1:?укажите ID Syncthing компьютера}"
CONFIG=$(ls /root/.local/state/syncthing/config.xml /root/.config/syncthing/config.xml 2>/dev/null | head -1)
[[ -n "$CONFIG" ]] || { echo "Нет config.xml Syncthing — запущен ли syncthing@root?"; exit 1; }

PC_ID="$PC_ID" API_KEY=$(grep -oP '<apikey>\K[^<]+' "$CONFIG") python3 - <<'EOF'
import json, os, urllib.request

KEY, PC = os.environ["API_KEY"], os.environ["PC_ID"].strip().upper()
BASE = "http://127.0.0.1:8384/rest"


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, headers={"X-API-Key": KEY},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


devices = call("GET", "/config/devices")
if not any(d["deviceID"] == PC for d in devices):
    call("POST", "/config/devices", {"deviceID": PC, "name": "lab-pc",
                                     "addresses": ["tcp://10.8.0.2:22000", "dynamic"]})
folder = call("GET", "/config/folders/esg-data")
if not any(d["deviceID"] == PC for d in folder["devices"]):
    folder["devices"].append({"deviceID": PC})
    call("PUT", "/config/folders/esg-data", folder)
print("ID этого сервера:", call("GET", "/system/status")["myID"])
EOF
echo "Компьютер добавлен. На компьютере примите папку «ESG data» и укажите вашу папку данных."
