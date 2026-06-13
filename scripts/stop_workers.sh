#!/usr/bin/env bash
# หยุด celery workers ของ dsl-auto ทั้งหมด (จาก pidfile + กวาด leftover)
set -uo pipefail

PIDFILE="/tmp/dslauto_workers.pids"
killed=0

if [ -f "$PIDFILE" ]; then
  while read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null && killed=$((killed+1))
  done < "$PIDFILE"
  rm -f "$PIDFILE"
fi

# fallback: กวาด worker ที่หลุด pidfile (เฉพาะ dslauto ของโปรเจกต์นี้)
pkill -f "celery -A app.worker.celery_app worker.*dslauto" 2>/dev/null || true

echo "stopped ($killed pids จาก pidfile)"
