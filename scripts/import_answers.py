"""Import เฉลย (correct_value / correct_index) จาก JSON → Redis answer_bank

Cache format (robust): เก็บทั้ง option.value + text_hash
  → ตอน lookup ใน automation:
       1. ลอง match by option.value (เร็ว)
       2. fallback match by text_hash (กัน SET random option.value ระหว่าง attempts)

JSON format ที่ dump_questions.py สร้าง:
{
  "questions": [
    {
      "q_hash": "abc123",
      "q_text": "คำถาม...",
      "options": [{"value": "8001", "text": "..."}, ...],
      "correct_value": "8002",     ← user ใส่ตรงนี้ (value ของ option ที่ถูก)
      "correct_index": null,       ← หรือใส่ index 0-3 ก็ได้
    }
  ]
}

Usage:
    python scripts/import_answers.py questions/dump.json
    python scripts/import_answers.py questions/dump.json --dry-run    # preview
    python scripts/import_answers.py questions/dump.json --force      # overwrite
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "stubs"))

import redis as sync_redis
from app.config import settings

REDIS_KEY = "dsl:answer_cache"


def text_hash(text: str) -> str:
    """SHA1 8 chars ของ option text — ใช้ match กัน SET random option.value"""
    normalized = " ".join((text or "").split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


def main():
    parser = argparse.ArgumentParser(description="Import answer keys from JSON to Redis")
    parser.add_argument("json_file")
    parser.add_argument("--dry-run", action="store_true", help="ไม่ save, แค่ preview")
    parser.add_argument("--force", action="store_true", help="overwrite ของเก่าใน Redis")
    args = parser.parse_args()

    path = Path(args.json_file)
    if not path.exists():
        print(f"❌ ไม่พบไฟล์ {path}")
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data.get("questions", data) if isinstance(data, dict) else data

    r = sync_redis.from_url(settings.redis_url, decode_responses=True)
    existing = r.hgetall(REDIS_KEY) or {}

    # Stats
    n_total = len(questions)
    n_no_answer = 0
    n_invalid = 0
    n_new = 0
    n_overwrite = 0
    n_skip_same = 0

    to_write = {}     # q_hash → correct_value
    errors = []

    for i, q in enumerate(questions):
        qh = q.get("q_hash")
        if not qh:
            errors.append(f"#{i}: missing q_hash")
            n_invalid += 1
            continue

        options = q.get("options", [])
        if not options:
            errors.append(f"#{i} ({qh}): no options")
            n_invalid += 1
            continue

        cv = q.get("correct_value")
        ci = q.get("correct_index")

        # ไม่มีเฉลย → ข้าม
        if cv is None and ci is None:
            n_no_answer += 1
            continue

        # ถ้าใส่แต่ index → map เป็น value
        if cv is None and ci is not None:
            try:
                ci = int(ci)
                if 0 <= ci < len(options):
                    cv = options[ci]["value"]
                else:
                    errors.append(f"#{i} ({qh}): correct_index {ci} เกิน range [0, {len(options)-1}]")
                    n_invalid += 1
                    continue
            except (ValueError, TypeError):
                errors.append(f"#{i} ({qh}): correct_index ไม่ใช่ int")
                n_invalid += 1
                continue

        # ตรวจว่า correct_value อยู่ใน options
        if not any(str(o.get("value")) == str(cv) for o in options):
            errors.append(
                f"#{i} ({qh}): correct_value '{cv}' ไม่อยู่ใน options "
                f"({[o.get('value') for o in options]})"
            )
            n_invalid += 1
            continue

        # ถ้าใส่ทั้ง cv + ci → ตรวจว่าตรง
        if q.get("correct_value") is not None and q.get("correct_index") is not None:
            try:
                ci_int = int(q["correct_index"])
                if 0 <= ci_int < len(options):
                    expected = options[ci_int]["value"]
                    if str(expected) != str(cv):
                        errors.append(
                            f"#{i} ({qh}): correct_value={cv} ขัด correct_index={ci_int} (option={expected})"
                        )
                        n_invalid += 1
                        continue
            except (ValueError, TypeError):
                pass

        # OK → คำนวณ text_hash ของ correct option แล้วเก็บเป็น JSON
        cv_str = str(cv)
        correct_opt = next((o for o in options if str(o.get("value")) == cv_str), None)
        correct_text = correct_opt.get("text", "") if correct_opt else ""
        th = text_hash(correct_text)
        new_value = json.dumps({"v": cv_str, "t": th}, ensure_ascii=False, separators=(",", ":"))

        old = existing.get(qh)
        # ตรวจเปรียบเทียบแบบ tolerant: parse old (อาจเป็น flat string หรือ JSON)
        old_v = None
        if old:
            try:
                old_parsed = json.loads(old)
                old_v = old_parsed.get("v") if isinstance(old_parsed, dict) else old
            except (ValueError, TypeError):
                old_v = old

        if old_v == cv_str:
            n_skip_same += 1
            continue
        if old is None:
            n_new += 1
        else:
            if not args.force:
                errors.append(f"#{i} ({qh}): มีของเก่า v='{old_v}' — ใช้ --force ถ้าจะ overwrite")
                continue
            n_overwrite += 1
        to_write[qh] = new_value

    # Summary
    print(f"📊 Summary")
    print(f"   total questions in JSON: {n_total}")
    print(f"   no answer yet:           {n_no_answer}")
    print(f"   invalid (skipped):       {n_invalid}")
    print(f"   already in Redis (same): {n_skip_same}")
    print(f"   will write new:          {n_new}")
    print(f"   will overwrite:          {n_overwrite}")
    print(f"   total to write:          {len(to_write)}")

    if errors:
        print(f"\n⚠️  Issues ({len(errors)}):")
        for e in errors[:20]:
            print(f"   {e}")
        if len(errors) > 20:
            print(f"   ... +{len(errors) - 20} more")

    if not to_write:
        print(f"\n💤 ไม่มีอะไรต้อง write")
        return

    if args.dry_run:
        print(f"\n🧪 DRY-RUN — ไม่ save จริง. ใช้คำสั่งโดยไม่มี --dry-run เพื่อ save")
        return

    # Write
    pipe = r.pipeline()
    pipe.hset(REDIS_KEY, mapping=to_write)
    pipe.execute()
    print(f"\n✅ save {len(to_write)} answers → Redis '{REDIS_KEY}'")
    print(f"   ตอนนี้ใน Redis: {r.hlen(REDIS_KEY)} ข้อ")


if __name__ == "__main__":
    main()
