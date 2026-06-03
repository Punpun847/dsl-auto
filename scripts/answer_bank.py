"""Manage answer bank — ดู/export/import/clear cache + จัดการ pending questions

Usage:
    # Cache management
    python scripts/answer_bank.py stats              # นับข้อ
    python scripts/answer_bank.py list               # ดูทั้งหมด (truncated)
    python scripts/answer_bank.py export out.json    # ดู
    python scripts/answer_bank.py import in.json     # นำเข้า
    python scripts/answer_bank.py clear              # ล้างทั้งหมด (confirm)
    python scripts/answer_bank.py delete <hash>      # ลบ key เดียว

    # Pending questions (จาก automation runtime)
    python scripts/answer_bank.py pending stats              # นับ pending
    python scripts/answer_bank.py pending list               # ดูคำถาม
    python scripts/answer_bank.py pending promote            # merge → questions/dump.json
    python scripts/answer_bank.py pending clear              # ล้าง pending file
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "stubs"))

import redis as sync_redis
from app.config import settings

REDIS_KEY = "dsl:answer_cache"


def r():
    return sync_redis.from_url(settings.redis_url, decode_responses=True)


def cmd_stats():
    n = r().hlen(REDIS_KEY)
    print(f"📊 answer_bank: {n} ข้อ")


def cmd_list():
    data = r().hgetall(REDIS_KEY) or {}
    for k, v in sorted(data.items()):
        print(f"  {k} → {v}")
    print(f"\nรวม {len(data)} ข้อ")


def cmd_export(path):
    data = r().hgetall(REDIS_KEY) or {}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 export {len(data)} ข้อ → {path}")


def cmd_import(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(f"❌ ไฟล์ {path} ไม่ใช่ JSON object")
        sys.exit(1)
    if not data:
        print(f"⚠️  ว่าง — ไม่ import")
        return
    cli = r()
    cli.hset(REDIS_KEY, mapping=data)
    print(f"✅ import {len(data)} ข้อ")


def cmd_clear():
    n = r().hlen(REDIS_KEY)
    if n == 0:
        print(f"answer_bank ว่างอยู่แล้ว")
        return
    ans = input(f"⚠️  ลบทั้ง {n} ข้อจาก answer_bank? พิมพ์ 'yes' เพื่อยืนยัน: ")
    if ans.strip().lower() == "yes":
        r().delete(REDIS_KEY)
        print(f"🗑  ลบเรียบร้อย")
    else:
        print(f"ยกเลิก")


def cmd_delete(h):
    if r().hdel(REDIS_KEY, h):
        print(f"🗑  ลบ {h}")
    else:
        print(f"❌ ไม่พบ key {h}")


# ───────────── Pending questions sub-commands ─────────────

def cmd_pending(*args):
    """python scripts/answer_bank.py pending <stats|list|promote|clear>"""
    from app.utils.pending_dump import read_pending, clear_pending, PENDING_FILE

    if not args:
        print("Usage: pending <stats|list|promote|clear>")
        sys.exit(1)
    sub = args[0]

    if sub == "stats":
        items = read_pending()
        print(f"📝 pending questions: {len(items)}")
        if items:
            print(f"   file: {PENDING_FILE}")
            # group by course
            by_course = {}
            for q in items:
                by_course.setdefault(q.get("course_id", "?"), []).append(q)
            print(f"   breakdown:")
            for cid, qs in sorted(by_course.items()):
                print(f"     {cid}: {len(qs)} ข้อ")
        return

    if sub == "list":
        items = read_pending()
        for q in items[:50]:
            print(f"  [{q.get('course_id', '?')}/{q.get('exam_type', '?')}] {q['q_hash']} | {q['q_text'][:80]}")
        if len(items) > 50:
            print(f"  ... +{len(items)-50} more")
        print(f"\nรวม {len(items)} ข้อ")
        return

    if sub == "promote":
        # Merge pending → questions/dump.json
        import json as _j
        items = read_pending()
        if not items:
            print("✅ pending ว่าง — ไม่มีอะไรต้อง promote")
            return

        dump_path = Path(__file__).parent.parent / "questions" / "dump.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if dump_path.exists():
            try:
                data = _j.loads(dump_path.read_text(encoding="utf-8"))
                for q in data.get("questions", []):
                    existing[q["q_hash"]] = q
            except Exception:
                pass

        new_count = 0
        for q in items:
            qh = q["q_hash"]
            if qh in existing:
                # merge metadata — preserve existing correct_value
                continue
            existing[qh] = {
                "q_hash": qh,
                "q_text": q.get("q_text"),
                "options": q.get("options", []),
                "correct_value": None,
                "correct_index": None,
                "notes": "from automation runtime",
                "course_id": q.get("course_id", ""),
                "course_title": "",
                "exam_type": q.get("exam_type", ""),
            }
            new_count += 1

        questions = list(existing.values())
        questions.sort(key=lambda x: (x.get("course_id", ""), x.get("exam_type", ""), x["q_hash"]))
        from datetime import datetime, timezone
        out = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(questions),
            "filled": sum(1 for q in questions if q.get("correct_value") or q.get("correct_index") is not None),
            "questions": questions,
        }
        dump_path.write_text(_j.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ promoted {new_count} ข้อใหม่ → {dump_path}")
        print(f"   total in dump.json: {len(questions)} ({out['filled']} filled, {len(questions)-out['filled']} pending)")
        print()
        print(f"📝 ขั้นตอนต่อไป:")
        print(f"   python scripts/make_prompt.py questions/dump.json --unanswered-only --chunk 30")
        print(f"   # paste prompt ไป Gemini → save response → apply")
        print(f"   python scripts/apply_answers.py questions/dump.json prompts/answers.txt --import")
        return

    if sub == "clear":
        n = clear_pending()
        print(f"🗑  ลบ pending file ({n} ข้อ)")
        return

    print(f"❌ ไม่รู้จัก sub-command '{sub}'")
    sys.exit(1)


COMMANDS = {
    "stats": (cmd_stats, 0),
    "list": (cmd_list, 0),
    "export": (cmd_export, 1),
    "import": (cmd_import, 1),
    "clear": (cmd_clear, 0),
    "delete": (cmd_delete, 1),
    "pending": (cmd_pending, -1),   # -1 = variadic
}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    fn, nargs = COMMANDS[sys.argv[1]]
    if nargs == -1:
        # variadic — pass ทุก arg ที่เหลือ
        fn(*sys.argv[2:])
    else:
        if len(sys.argv) < nargs + 2:
            print(f"❌ {sys.argv[1]} ต้องการ {nargs} args")
            sys.exit(1)
        fn(*sys.argv[2:2+nargs])
