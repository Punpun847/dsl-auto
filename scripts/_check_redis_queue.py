"""Check what's in Celery Redis queue"""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

import redis as redis_lib
import json

rdb = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)

# Check celery queue
queue_len = rdb.llen("celery")
print(f"Celery queue length: {queue_len}")

if queue_len > 0:
    # Peek at first item without removing
    item = rdb.lindex("celery", 0)
    try:
        data = json.loads(item)
        body_str = data.get("body", "")
        import base64
        body = json.loads(base64.b64decode(body_str).decode())
        print(f"Task: {data.get('headers', {}).get('task', 'unknown')}")
        print(f"ID: {data.get('headers', {}).get('id', 'unknown')}")
        print(f"Args: {body[0] if body else 'n/a'}")
    except Exception as e:
        print(f"Raw: {item[:200]}")
        print(f"Parse error: {e}")

# Check for any unacknowledged tasks
print(f"\nAll Redis keys matching 'celery*': {rdb.keys('celery*')[:10]}")
print(f"All keys matching 'unacked*': {rdb.keys('unacked*')[:5]}")
