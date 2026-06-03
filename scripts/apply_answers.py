"""รับ JSON response จาก LLM → patch ลง dump.json + ตรวจ validity

Usage:
    # paste Gemini response → save เป็น answers.txt → apply
    python scripts/apply_answers.py questions/dump.json answers.txt

    # apply หลายไฟล์รวมกัน (จาก chunk)
    python scripts/apply_answers.py questions/dump.json answers_1.txt answers_2.txt

    # dry-run preview
    python scripts/apply_answers.py questions/dump.json answers.txt --dry-run

    # apply + import ต่อทันที
    python scripts/apply_answers.py questions/dump.json answers.txt --import
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def extract_json(text: str) -> dict:
    """ดึง JSON object จาก text ที่อาจมี markdown / คำอธิบายปน
    รองรับ:
      - JSON ดิบ {"...": "..."}
      - ใน markdown ```json {...} ```
      - มี text นำ/ท้าย
    """
    text = text.strip()

    # ลบ markdown code block
    if "```" in text:
        # match ```json {...} ``` หรือ ``` {...} ```
        m = re.search(r"```(?:json|JSON)?\s*\n?(\{[\s\S]*?\})\s*\n?```", text)
        if m:
            text = m.group(1)

    # หา outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("ไม่เจอ JSON object ใน text")
    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        # ลอง relaxed — บางที AI ใส่ trailing comma หรือ comments
        # remove // ... comments
        cleaned = re.sub(r"//[^\n]*", "", candidate)
        # remove trailing commas
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"JSON parse fail: {e}\nContent: {candidate[:200]}")


def main():
    parser = argparse.ArgumentParser(description="Apply LLM answers to dump.json")
    parser.add_argument("dump_file", help="path to dump.json")
    parser.add_argument("answer_files", nargs="+",
                        help="ไฟล์ที่มี JSON response จาก LLM (1 ไฟล์ขึ้นไป)")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview ไม่ save")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="import_answers.py ต่อหลัง apply")
    args = parser.parse_args()

    dump_path = Path(args.dump_file)
    data = json.loads(dump_path.read_text(encoding="utf-8"))
    questions = data.get("questions", [])
    by_hash = {q["q_hash"]: q for q in questions}

    # รวบรวม answers จากทุกไฟล์
    all_answers: dict = {}
    for f in args.answer_files:
        path = Path(f)
        if not path.exists():
            print(f"❌ ไม่พบไฟล์ {path}")
            continue
        text = path.read_text(encoding="utf-8")
        try:
            ans = extract_json(text)
        except ValueError as e:
            print(f"❌ {path}: {e}")
            continue
        print(f"📄 {path}: {len(ans)} answers")
        all_answers.update(ans)

    if not all_answers:
        print(f"\n💤 ไม่มี answers ให้ apply")
        return

    # Validate + apply
    matched = 0
    unmatched_hash = 0
    invalid_value = 0
    skipped_existing = 0

    for q_hash, correct_value in all_answers.items():
        q = by_hash.get(q_hash)
        if not q:
            unmatched_hash += 1
            continue

        # ตรวจ value อยู่ใน options
        options = q.get("options", [])
        valid_values = [str(o.get("value")) for o in options]
        cv_str = str(correct_value)
        if cv_str not in valid_values:
            invalid_value += 1
            print(f"  ⚠️  {q_hash}: '{cv_str}' ไม่อยู่ใน options {valid_values}")
            continue

        # ถ้ามี correct_value อยู่แล้ว — skip (ถ้าไม่ใช่ dry-run)
        if q.get("correct_value") and str(q["correct_value"]) == cv_str:
            skipped_existing += 1
            continue

        q["correct_value"] = cv_str
        q["correct_index"] = next(
            (i for i, o in enumerate(options) if str(o.get("value")) == cv_str),
            None,
        )
        matched += 1

    print(f"\n📊 Summary")
    print(f"   total answers ใน LLM response: {len(all_answers)}")
    print(f"   ✅ matched + applied:          {matched}")
    print(f"   ⏭  skip (มีของเดิม):          {skipped_existing}")
    print(f"   ❌ unmatched q_hash:           {unmatched_hash}")
    print(f"   ⚠️  invalid value:              {invalid_value}")
    print()

    # Stats สรุปจำนวนที่ filled
    total = len(questions)
    filled = sum(1 for q in questions if q.get("correct_value") is not None)
    print(f"   📋 dump.json: {filled}/{total} ข้อมีเฉลย ({filled / total * 100:.0f}%)")

    if args.dry_run:
        print(f"\n🧪 DRY-RUN — ไม่ save จริง")
        return

    # update metadata
    data["filled"] = filled
    from datetime import datetime, timezone
    data["last_apply_at"] = datetime.now(timezone.utc).isoformat()

    dump_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 saved → {dump_path}")

    if args.do_import:
        print(f"\n🔄 รัน import_answers.py ต่อ...")
        result = subprocess.run(
            [sys.executable, "scripts/import_answers.py", str(dump_path)],
            cwd=Path(__file__).parent.parent,
        )
        if result.returncode != 0:
            print(f"❌ import fail (exit {result.returncode})")


if __name__ == "__main__":
    main()
