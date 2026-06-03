"""Check unacknowledged Celery tasks in Redis"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import redis as redis_lib
import json, base64

rdb = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)

# unacked is a hash: {delivery_tag -> (msg, channel, delivery_tag)}
unacked = rdb.hgetall("unacked")
print(f"Unacked tasks: {len(unacked)}")
for tag, val in unacked.items():
    try:
        parsed = json.loads(val)
        msg_body = parsed[0]
        if isinstance(msg_body, dict):
            headers = msg_body.get("headers", {})
            body_b64 = msg_body.get("body", "")
            try:
                body = json.loads(base64.b64decode(body_b64).decode())
                args = body[0] if body else []
            except:
                args = "?"
            print(f"  tag={tag[:12]}... task={headers.get('task')} id={headers.get('id','?')[:12]}... args={args}")
        else:
            print(f"  tag={tag[:12]}... raw={str(val)[:100]}")
    except Exception as e:
        print(f"  tag={tag[:12]}... error={e}")

# unacked_index is a zset
idx = rdb.zrange("unacked_index", 0, -1, withscores=True)
print(f"\nUnacked index entries: {len(idx)}")
for item in idx:
    print(f"  {item}")
