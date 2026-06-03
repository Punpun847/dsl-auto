import os
import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
n = r.hlen("dsl:answer_cache")
print(f"answer_cache size: {n} ข้อ")

# list backup files
for path in ["questions/answer_bank_2026-05-26.json", "questions/dump.json"]:
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    print(f"  {path}: exists={exists} size={size:,} bytes")
