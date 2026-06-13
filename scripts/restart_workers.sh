#!/usr/bin/env bash
# รีสตาร์ท celery workers — หยุดของเก่าแล้วเริ่มใหม่ N ตัว (default 4)
set -uo pipefail

N="${1:-4}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$DIR/stop_workers.sh"
sleep 2
bash "$DIR/start_workers.sh" "$N"
