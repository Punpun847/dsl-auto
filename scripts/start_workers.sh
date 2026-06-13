#!/usr/bin/env bash
# รัน celery workers ของ dsl-auto N ตัว (default 4) แบบ background
# pid เก็บใน /tmp/dslauto_workers.pids · log ที่ /tmp/celery_dslauto{n}.log
set -euo pipefail

N="${1:-4}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="/tmp/dslauto_workers.pids"
cd "$ROOT"

# ── guard: ถ้ามี worker ยังรันอยู่ ไม่ start ซ้ำ (ใช้ restart ถ้าต้องการ) ──
if [ -f "$PIDFILE" ]; then
  alive=0
  while read -r pid; do [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=$((alive+1)); done < "$PIDFILE"
  if [ "$alive" -gt 0 ]; then
    echo "มี $alive worker รันอยู่แล้ว — ข้าม (ใช้ stop/restart ถ้าต้องการ)"
    exit 0
  fi
fi

: > "$PIDFILE"
for n in $(seq 1 "$N"); do
  PYTHONPATH="$ROOT" nohup python3 -m celery -A app.worker.celery_app worker \
    --pool=solo --concurrency=1 -n "dslauto${n}@%h" --loglevel=info \
    > "/tmp/celery_dslauto${n}.log" 2>&1 &
  echo $! >> "$PIDFILE"
done

echo "started $N workers (pids: $(tr '\n' ' ' < "$PIDFILE"))"
