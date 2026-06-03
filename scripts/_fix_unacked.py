"""ย้าย unacked tasks กลับเข้า queue (rescue stuck tasks)"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import redis as redis_lib
import json

rdb = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)

unacked = rdb.hgetall("unacked")
print(f"Found {len(unacked)} unacked tasks — moving back to queue...")

pushed = 0
seen_task_ids = set()

for tag, val in unacked.items():
    try:
        parsed = json.loads(val)
        msg = parsed[0]  # The original message
        headers = msg.get("headers", {})
        task_id = headers.get("id", "")

        # Deduplicate by task_id
        if task_id in seen_task_ids:
            print(f"  SKIP duplicate task_id={task_id[:8]}...")
            # Remove from unacked
            rdb.hdel("unacked", tag)
            rdb.zrem("unacked_index", tag)
            continue
        seen_task_ids.add(task_id)

        # Re-queue the message
        rdb.rpush("celery", json.dumps(msg))
        pushed += 1
        print(f"  ✅ re-queued task={headers.get('task')} id={task_id[:8]}...")

        # Remove from unacked
        rdb.hdel("unacked", tag)
        rdb.zrem("unacked_index", tag)
    except Exception as e:
        print(f"  ❌ error: {e}")

print(f"\nQueue length now: {rdb.llen('celery')}")
print(f"Unacked remaining: {rdb.hlen('unacked')}")
