#!/usr/bin/env bash
# Связывает Syncthing сервера с компьютером лаборатории и открывает ему папку данных.
#   sudo /opt/ESG_XAI/deploy/yandex/link-pc.sh <ID устройства компьютера>
# ID — в Syncthing на компьютере: «Действия → Показать ID».
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
PC_ID="${1:?укажите ID Syncthing компьютера}"

if ! syncthing cli config devices list | grep -qx "$PC_ID"; then
  syncthing cli config devices add --device-id "$PC_ID" --name lab-pc --addresses tcp://10.8.0.2:22000,dynamic
fi
if ! syncthing cli config folders esg-data devices list | grep -qx "$PC_ID"; then
  syncthing cli config folders esg-data devices add --device-id "$PC_ID"
fi

echo "Компьютер добавлен. На компьютере примите папку «ESG data» и укажите вашу папку данных."
echo "ID этого сервера: $(syncthing cli show system | grep -oP '"myID":\s*"\K[^"]+')"
