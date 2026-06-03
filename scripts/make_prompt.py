"""สร้าง prompt สำหรับ paste ไป Gemini / ChatGPT / Claude

อ่าน dump.json → format เป็น prompt ภาษาไทยที่สั่งให้ AI ตอบ
output เป็นไฟล์ prompt.txt หรือ stdout (copy paste ได้)

Usage:
    # default: prompts/prompt.txt
    python scripts/make_prompt.py questions/dump.json

    # custom output
    python scripts/make_prompt.py questions/dump.json --out my-prompt.txt

    # split เป็นหลายไฟล์ (กรณี prompt ยาวเกิน context)
    python scripts/make_prompt.py questions/dump.json --chunk 20

    # เฉพาะข้อที่ยังไม่มีเฉลย
    python scripts/make_prompt.py questions/dump.json --unanswered-only

    # filter เฉพาะ course
    python scripts/make_prompt.py questions/dump.json --course 1905
"""
import argparse
import json
import sys
from pathlib import Path


PROMPT_HEADER = """คุณเป็นผู้เชี่ยวชาญด้านการเงิน การลงทุน การวางแผนการเงินส่วนบุคคล
ภาษีอากร เศรษฐศาสตร์ และทักษะการบริหารธุรกิจ

ภารกิจ: ตอบข้อสอบ multiple choice ของ SET e-Learning (ตลาดหลักทรัพย์ฯ) อย่างแม่นยำ
- อ่านโจทย์ + ตัวเลือกทั้งหมดให้ดี
- ระบุคำตอบที่ถูกต้องที่สุด 1 ข้อต่อโจทย์
- คำถามมักจะมีคำว่า "ไม่ใช่" / "ที่ผิด" / "ที่ถูกต้อง" — ให้อ่านเข้าใจก่อนตอบ
- ตอบแม้ไม่แน่ใจ 100% (ตอบที่น่าจะเป็นไปได้มากที่สุด)

รูปแบบคำตอบ (สำคัญมาก!):
ตอบเป็น JSON เพียงอย่างเดียว ห้ามมีข้อความอื่น
รูปแบบ:
{
  "<q_hash1>": "<value ของ option ที่ถูก>",
  "<q_hash2>": "<value ของ option ที่ถูก>",
  ...
}

ตัวอย่าง:
{
  "0754b696ed7c": "145023",
  "1465de062b3a": "145035"
}

ห้ามใช้ markdown code block (```), ตอบ JSON ดิบเลย

ข้อสอบ (รวม %COUNT% ข้อ):
"""

QUESTION_TEMPLATE = """
═══ ข้อ {n} — q_hash: {q_hash} ═══
หลักสูตร: {course_title}
{q_text}

ตัวเลือก:
{options}
"""


def format_options(options):
    lines = []
    for o in options:
        v = o.get("value", "?")
        t = o.get("text", "")
        lines.append(f"  • value=\"{v}\"  →  {t}")
    return "\n".join(lines)


def build_prompt(questions, chunk_idx=None, total_chunks=None):
    """สร้าง prompt text จากชุดคำถาม"""
    header = PROMPT_HEADER.replace("%COUNT%", str(len(questions)))
    if chunk_idx is not None:
        header += f"\n[ชุดที่ {chunk_idx}/{total_chunks}]\n"

    body = []
    for i, q in enumerate(questions, start=1):
        body.append(QUESTION_TEMPLATE.format(
            n=i,
            q_hash=q["q_hash"],
            q_text=q["q_text"],
            course_title=q.get("course_title", "—"),
            options=format_options(q.get("options", [])),
        ))

    footer = f"\n\n--- จบข้อสอบ — ตอบ JSON เพียงอย่างเดียว ({len(questions)} ข้อ) ---\n"
    return header + "".join(body) + footer


def main():
    parser = argparse.ArgumentParser(description="Generate LLM prompt from dump.json")
    parser.add_argument("dump_file", help="path to dump.json")
    parser.add_argument("--out", default=None,
                        help="output file (default: prompts/prompt.txt หรือ chunk_N.txt)")
    parser.add_argument("--chunk", type=int, default=None,
                        help="แบ่งเป็นหลายชุด ชุดละ N ข้อ (กัน prompt ยาวเกิน)")
    parser.add_argument("--unanswered-only", action="store_true",
                        help="เฉพาะข้อที่ยังไม่มี correct_value/correct_index")
    parser.add_argument("--course", default=None,
                        help="filter เฉพาะ course_id ที่ระบุ")
    parser.add_argument("--stdout", action="store_true",
                        help="พิมพ์ลง stdout แทนเขียนไฟล์")
    args = parser.parse_args()

    data = json.loads(Path(args.dump_file).read_text(encoding="utf-8"))
    questions = data.get("questions", data) if isinstance(data, dict) else data

    # Filter
    if args.unanswered_only:
        questions = [q for q in questions
                     if q.get("correct_value") is None and q.get("correct_index") is None]
    if args.course:
        questions = [q for q in questions if str(q.get("course_id")) == str(args.course)]

    if not questions:
        print("⚠️  ไม่มีข้อสอบที่ match filter")
        return

    # Chunk
    chunks = []
    if args.chunk and args.chunk > 0:
        for i in range(0, len(questions), args.chunk):
            chunks.append(questions[i:i + args.chunk])
    else:
        chunks = [questions]

    out_dir = Path(args.out).parent if args.out else Path("prompts")
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, chunk_qs in enumerate(chunks, start=1):
        text = build_prompt(
            chunk_qs,
            chunk_idx=idx if len(chunks) > 1 else None,
            total_chunks=len(chunks) if len(chunks) > 1 else None,
        )

        if args.stdout:
            print(text)
        else:
            if args.out and len(chunks) == 1:
                out_path = Path(args.out)
            elif args.out:
                # multi-chunk + custom out → append _N
                p = Path(args.out)
                out_path = p.parent / f"{p.stem}_{idx}{p.suffix}"
            else:
                out_path = out_dir / (
                    f"prompt_{idx}.txt" if len(chunks) > 1 else "prompt.txt"
                )
            out_path.write_text(text, encoding="utf-8")
            chars = len(text)
            est_tokens = chars // 3  # rough Thai estimate
            print(f"💾 chunk {idx}/{len(chunks)}: {len(chunk_qs):>3} ข้อ → {out_path}  ({chars:,} chars ≈ {est_tokens:,} tokens)")

    print(f"\n📋 รวม {len(questions)} ข้อใน {len(chunks)} ชุด")
    print(f"\n📝 ขั้นตอนต่อไป:")
    print(f"  1. เปิดไฟล์ใน prompts/ — copy ทั้งหมด")
    print(f"  2. paste ไป Gemini / ChatGPT / Claude")
    print(f"  3. copy JSON ที่ได้กลับมาใส่ไฟล์ (เช่น answers.json)")
    print(f"  4. python scripts/apply_answers.py questions/dump.json answers.json")


if __name__ == "__main__":
    main()
