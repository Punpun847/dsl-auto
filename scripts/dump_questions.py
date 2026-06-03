"""Dump exam questions เป็น JSON — ไม่ submit, ไม่ตอบ

Workflow:
  1. Login บัญชี 2 ที่ยังไม่ได้ทำ
  2. ต่อ course: enroll + mark topics → เปิด post-test/exam page → scrape questions
  3. Save เป็น JSON พร้อม field correct_value = null (รอ user เติม)
  4. (Optional) รัน N รอบ — SET random ข้อจาก pool → merge dedup → ได้ครบ pool

Output: questions/<course_id>.json  หรือไฟล์เดียวรวม

Usage:
    # ❗ แนะนำ — smart mode (auto-stop เมื่อครบ pool)
    python scripts/dump_questions.py <NID> <PWD> 666 --smart

    # หลาย course + smart
    python scripts/dump_questions.py <NID> <PWD> 666 1941 1942 --smart

    # Fixed N รอบ (เร็ว แต่ไม่ครอบคลุม pool ถ้าเล็กไป)
    python scripts/dump_questions.py <NID> <PWD> 666 --repeat 10

    # Smart + custom patience (default หยุดหลังไม่เจอข้อใหม่ 3 รอบ)
    python scripts/dump_questions.py <NID> <PWD> 666 --smart --smart-patience 5

    # custom output path
    python scripts/dump_questions.py <NID> <PWD> 666 --smart --out my-questions.json

Coverage estimate (SET random เลือก N ข้อ จาก pool ใหญ่):
    pool=30, exam=10:  5 รอบ→87%  10 รอบ→98%  15 รอบ→99.8%
    pool=20, exam=10:  5 รอบ→97%  8 รอบ→99.6%
    pool=50, exam=10: 10 รอบ→89%  20 รอบ→98.8%  30 รอบ→99.9%
"""
import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))

os.environ["DSL_DEBUG"] = "0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
for noisy in ("asyncio", "urllib3", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def question_hash(text: str) -> str:
    """ตรงกับ DSLClient._question_hash"""
    normalized = " ".join((text or "").split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


async def scrape_exam_questions(client, exam_url: str) -> List[Dict]:
    """เปิดหน้า exam → scrape question + options (ไม่ submit!)
    คืน list ของ {q_hash, q_text, options}"""
    await client.page.goto(exam_url, wait_until="domcontentloaded", timeout=20_000)
    await asyncio.sleep(3)

    # คลิก "เริ่มแบบทดสอบ" ถ้ามี
    await client.page.evaluate("""() => {
        for (const el of document.querySelectorAll('button, a, .btn')) {
            const t = (el.innerText || '').trim();
            if (t === 'เริ่มแบบทดสอบ' || t === 'เริ่มทำแบบทดสอบ' ||
                t.startsWith('เริ่มทำ') || t.startsWith('เริ่มแบบ')) {
                el.disabled = false; el.click(); return;
            }
        }
    }""")
    await asyncio.sleep(3)

    # poll หา radio
    for _ in range(15):
        n = await client.page.evaluate("() => document.querySelectorAll('input[type=\"radio\"]').length")
        if n > 0:
            break
        await asyncio.sleep(1.5)
    if n == 0:
        return []

    # Scrape question + options (เหมือน _read_exam_dom ของ DSLClient)
    raw = await client.page.evaluate("""() => {
        const out = [];
        const seen = new Set();
        document.querySelectorAll('input[type="radio"]').forEach(r => {
            if (seen.has(r.name)) return;
            seen.add(r.name);
            let parent = r.closest('.question, .form-group, .quiz-question, li, fieldset, .panel');
            if (!parent) parent = r.parentElement?.parentElement;
            const qNode = parent?.querySelector('legend, h3, h4, h5, .question-title, p:first-of-type, label');
            const qText = (qNode?.innerText || parent?.innerText || '').trim();
            const opts = [];
            document.querySelectorAll(`input[type="radio"][name="${r.name}"]`).forEach(opt => {
                const lbl = opt.closest('label') || document.querySelector(`label[for="${opt.id}"]`);
                opts.push({
                    value: opt.value,
                    text: (lbl?.innerText || '').trim().slice(0, 300),
                });
            });
            out.push({q_name: r.name, q_text: qText.slice(0, 600), options: opts});
        });
        return out;
    }""")

    # Add q_hash + correct_value placeholder
    result = []
    for q in raw:
        qh = question_hash(q["q_text"])
        result.append({
            "q_hash": qh,
            "q_text": q["q_text"],
            "options": q["options"],
            "correct_value": None,    # ← user เติม
            "correct_index": None,    # ← หรือใส่ index (0-based) ก็ได้
            "notes": "",
        })
    return result


async def detect_group(client) -> str:
    """ตรวจ group ปัจจุบันจาก URL — SETGroup, SETStudentLoan, อื่นๆ"""
    url = client.page.url
    import re as _re
    m = _re.search(r"elearning\.set\.or\.th/(\w+)", url)
    return m.group(1) if m else "SETGroup"


async def list_courses_in_group(client, group: str, max_pages: int = 30) -> List[Dict]:
    """List ทุก course ในกลุ่มผ่าน /list?page=N

    SET /list ใช้ query string ?page=N — ผมต้องวนใส่ explicit ไม่ใช่ scroll
    """
    base_url = f"https://elearning.set.or.th/{group}/list"
    all_courses = []
    seen_ids = set()

    for page_num in range(1, max_pages + 1):
        url = f"{base_url}?page={page_num}"
        print(f"  📄 page {page_num}: {url}")
        await client.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

        try:
            await client.page.wait_for_selector("a.card-course", timeout=8_000)
        except Exception:
            print(f"  ⚠️  ไม่เจอ cards — หยุดที่หน้า {page_num}")
            break

        page_courses = await client.page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a.card-course'))
                .map(card => {
                    const url = card.href || '';
                    const idMatch = url.match(/courses\\/(\\d+)/);
                    const text = card.innerText || '';
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    return {
                        id: idMatch ? idMatch[1] : null,
                        code: lines[0] || '',
                        title: lines[2] || lines[1] || '',
                    };
                }).filter(c => c.id);
        }""")

        # detect end — ถ้าหน้าใหม่มี id ซ้ำกับหน้าก่อนทั้งหมด → จบ
        new_in_page = sum(1 for c in page_courses if c["id"] not in seen_ids)
        if new_in_page == 0 and page_num > 1:
            print(f"  🛑 หน้า {page_num} ไม่มี id ใหม่ — จบ pagination")
            break

        for c in page_courses:
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                all_courses.append(c)

        print(f"     เจอ {len(page_courses)} cards ({new_in_page} ใหม่, รวม {len(all_courses)} unique)")

    return all_courses


async def dump_one_course(
    client,
    course_id: str,
    group: str = "SETStudentLoan",
    repeat: int = 1,
    smart: bool = False,
    smart_patience: int = 3,
    max_repeat: int = 30,
) -> List[Dict]:
    """Dump questions ของ 1 course (group สามารถระบุได้)"""
    # URL base ตาม group — ไม่ใช้ SET_BASE ที่ hardcode SETStudentLoan
    set_base = f"https://elearning.set.or.th/{group}"

    print(f"\n{'━' * 60}")
    print(f"🎯 Dumping course {course_id} (group={group}) "
          f"({'smart patience=' + str(smart_patience) if smart else f'{repeat} รอบ'})")
    print(f"{'━' * 60}")

    course_api = f"/api/site/groups/{group}/courses/{course_id}"

    # ดึง enroll_id
    course_data = await client.page.evaluate(f"""async () => {{
        const r = await fetch('{course_api}',
            {{credentials:'include', headers:{{'X-Requested-With':'XMLHttpRequest'}}}});
        return r.ok ? r.json() : null;
    }}""")
    if not course_data:
        print(f"  ❌ course {course_id} ไม่พบใน group {group}")
        return []

    title = course_data.get("title", course_id)
    enroll_id = course_data.get("enroll_id")
    print(f"  📚 {title}")

    # Enroll ถ้ายังไม่ลง
    if not enroll_id:
        print(f"  📝 enrolling...")
        await client.page.evaluate(f"""async () => {{
            const xsrf = document.cookie.split(';').map(c=>c.trim().split('=')).find(([k])=>k==='XSRF-TOKEN');
            const h = {{
                'X-Requested-With':'XMLHttpRequest',
                'X-XSRF-TOKEN': xsrf ? decodeURIComponent(xsrf[1]) : '',
                'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
            }};
            await fetch('/api/site/enroll2learning', {{
                method:'POST', headers:h, credentials:'include',
                body:'cid={course_id}&tid=&type=&pid=&ftype=',
            }});
        }}""")
        await asyncio.sleep(2)
        course_data = await client.page.evaluate(f"""async () => {{
            const r = await fetch('{course_api}',
                {{credentials:'include', headers:{{'X-Requested-With':'XMLHttpRequest'}}}});
            return r.json();
        }}""")
        enroll_id = course_data.get("enroll_id")

    if not enroll_id:
        print(f"  ❌ enroll fail")
        return []

    # Mark topics complete (ปลดล็อก exam)
    print(f"  🔧 marking topics complete (เพื่อปลดล็อก exam)...")
    enroll_data = await client.page.evaluate(f"""async () => {{
        const r = await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}});
        return r.json();
    }}""")
    # extract leaf topics
    topics = []
    def _extract(nodes):
        for n in (nodes or []):
            children = n.get("parent", [])
            if isinstance(children, list) and children:
                _extract(children)
            else:
                e2t = n.get("enroll2topic") or {}
                topics.append({"id": n["id"], "e2t_id": e2t.get("id"),
                              "pct": int(n.get("percentage") or 0)})
    _extract(enroll_data.get("topics") or [])

    incomplete_topics = [t for t in topics if t["pct"] < 100]
    if incomplete_topics:
        print(f"     marking {len(incomplete_topics)} topics...")
        for t in incomplete_topics:
            tid, e2t_id = t["id"], t["e2t_id"]
            # stage if missing
            if not e2t_id:
                await client.page.evaluate(f"""async () => {{
                    const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                    await fetch('/api/site/enroll2topic_stage', {{
                        method:'POST', headers:h, credentials:'include',
                        body:'enroll={enroll_id}&topics={tid}',
                    }});
                }}""")
            # view
            await client.page.evaluate(f"""async () => {{
                const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                await fetch('/api/site/enroll/views', {{
                    method:'POST', headers:h, credentials:'include',
                    body:'id=&enroll_id={enroll_id}&topics_id={tid}&state=vod',
                }});
            }}""")
            # refetch e2t_id
            if not e2t_id:
                refetch = await client.page.evaluate(f"""async () => (await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}})).json()""")
                def find_e2t(nodes):
                    for n in (nodes or []):
                        if isinstance(n.get('parent'), list) and n.get('parent'):
                            r = find_e2t(n['parent'])
                            if r: return r
                        elif n.get('id') == tid:
                            return (n.get('enroll2topic') or {}).get('id')
                    return None
                e2t_id = find_e2t(refetch.get('topics') or [])
            if e2t_id:
                await client.page.evaluate(f"""async () => {{
                    const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                    await fetch('/api/site/enroll2topic_duration', {{
                        method:'POST', headers:h, credentials:'include',
                        body:'id={e2t_id}&duration=0',
                    }});
                    await fetch('/api/site/enroll2topic_status', {{
                        method:'POST', headers:h, credentials:'include',
                        body:'id={e2t_id}&status=1',
                    }});
                }}""")
        print(f"     ✅ marked")

    # Dump exam pages — รัน `repeat` รอบเพื่อ cover pool ทั้งหมด
    all_questions = {}  # q_hash → question dict (dedup ข้าม exam_type ด้วย)

    for exam_type in ["post-test", "exam"]:
        url = f"{set_base}/enroll/{enroll_id}/exam/{exam_type}"
        seen_in_exam = set()  # q_hash ที่เจอใน exam_type นี้
        consecutive_no_new = 0  # นับ smart-mode
        rounds_done = 0

        max_rounds = max_repeat if smart else repeat
        while rounds_done < max_rounds:
            rounds_done += 1
            label = f"smart {rounds_done}" if smart else f"{rounds_done}/{repeat}"
            print(f"  📥 scraping {exam_type} (รอบ {label})...")

            try:
                qs = await scrape_exam_questions(client, url)
            except Exception as e:
                print(f"     ⚠️  error: {e}")
                consecutive_no_new += 1
                if smart and consecutive_no_new >= smart_patience:
                    print(f"     🛑 smart-stop: error ติด {smart_patience} รอบ")
                    break
                continue

            if not qs:
                print(f"     ⚠️  ไม่เจอ question — หยุด exam_type นี้")
                break

            new_this_round = 0
            for q in qs:
                q["course_id"] = course_id
                q["course_title"] = title
                q["exam_type"] = exam_type
                if q["q_hash"] not in all_questions:
                    all_questions[q["q_hash"]] = q
                    new_this_round += 1
                seen_in_exam.add(q["q_hash"])

            # Coverage estimate (Coupon Collector inverse)
            # ถ้ามี k ข้อ unique, รัน n รอบ, แต่ละรอบ m ข้อ → estimate pool size
            n_unique = len(seen_in_exam)
            n_per_round = len(qs)
            pool_est = _estimate_pool_size(rounds_done, n_per_round, n_unique)
            coverage_pct = (n_unique / pool_est * 100) if pool_est else 100

            print(f"     ได้ {len(qs)} ข้อ ({new_this_round} ใหม่, "
                  f"unique {n_unique}, estimate pool ≈ {pool_est}, coverage ≈ {coverage_pct:.0f}%)")

            # Smart-mode: stop ถ้าไม่เจอข้อใหม่ติดกัน
            if new_this_round == 0:
                consecutive_no_new += 1
                if smart and consecutive_no_new >= smart_patience:
                    print(f"     🛑 smart-stop: ไม่เจอข้อใหม่ {smart_patience} รอบติด — น่าจะครบ pool แล้ว")
                    break
            else:
                consecutive_no_new = 0

            await asyncio.sleep(2)  # กัน rate-limit

    out = list(all_questions.values())
    print(f"  💾 รวม {len(out)} ข้อ unique จาก course {course_id}")
    return out


def _estimate_pool_size(rounds: int, per_round: int, unique_seen: int) -> int:
    """ประมาณ pool size จากผล scrape (Coupon Collector inverse)

    ใช้ heuristic: ถ้า unique มากกว่า per_round → คาดว่า pool ≥ unique
    """
    if rounds <= 0 or per_round <= 0:
        return unique_seen
    # ถ้ายังไม่ converge — pool > unique
    # ถ้า per_round รอบล่าสุดได้ข้อใหม่น้อย → ใกล้ครบ pool
    # heuristic ง่าย: assume pool ≈ unique × (1 + 1/rounds)
    # ปลอดภัยคืน max(unique, ที่คาด)
    if unique_seen <= per_round:
        return per_round  # อย่างน้อย pool = per_round
    # rough estimate
    return max(unique_seen, int(unique_seen * 1.1))


async def main():
    parser = argparse.ArgumentParser(description="Dump SET exam questions to JSON (no submit)")
    parser.add_argument("user", help="NID (DSL mode) หรือ email (SET-direct mode)")
    parser.add_argument("pwd")
    parser.add_argument("courses", nargs="+", help="course IDs (เช่น 666 1941)")
    parser.add_argument("--repeat", type=int, default=5,
                        help="(fixed mode) จำนวนรอบ scrape ต่อ exam_type (default 5)")
    parser.add_argument("--smart", action="store_true",
                        help="(แนะนำ) auto-stop เมื่อไม่เจอข้อใหม่ติดกัน (Coupon Collector)")
    parser.add_argument("--smart-patience", type=int, default=3,
                        help="smart mode: stop หลังไม่เจอข้อใหม่กี่รอบติด (default 3)")
    parser.add_argument("--max-repeat", type=int, default=30,
                        help="smart mode: cap รอบสูงสุดต่อ exam_type (default 30)")
    parser.add_argument("--set-direct", action="store_true",
                        help="login ตรงที่ member.set.or.th (ใช้ email/password — ไม่ผ่าน DSL)")
    parser.add_argument("--group", default=None,
                        help="SET group (SETGroup/SETStudentLoan/อื่นๆ) — default auto-detect จาก URL")
    parser.add_argument("--list-only", action="store_true",
                        help="แค่ list courses ใน group, ไม่ dump")
    parser.add_argument("--out", default="questions/dump.json",
                        help="output path (merge กับไฟล์เดิม)")
    args = parser.parse_args()

    # auto-detect: ถ้า user มี '@' → SET-direct mode
    if "@" in args.user and not args.set_direct:
        print(f"🔄 detected email format → auto-enable --set-direct")
        args.set_direct = True

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # โหลดของเก่า (merge)
    existing = {}
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            for q in data.get("questions", []):
                existing[q["q_hash"]] = q
            print(f"📂 โหลดของเก่า {len(existing)} ข้อจาก {out_path}")
        except Exception:
            pass

    from app.worker.dsl_client import DSLClient

    async with DSLClient(headless=True) as client:
        if args.set_direct:
            print(f"🔑 login SET-direct (member.set.or.th)...")
            if not await client.login_set(args.user, args.pwd):
                print(f"❌ SET login fail: {client.last_error}")
                return
            print(f"✅ SET login OK (ไม่ต้อง SSO)")
        else:
            print(f"🔑 login DSL portal (กยศ.)...")
            if not await client.login(args.user, args.pwd):
                print(f"❌ DSL login fail: {client.last_error}")
                return
            if not await client.goto_set():
                print(f"❌ SSO fail")
                return
            print(f"✅ SSO SET OK")

        # Auto-detect group
        group = args.group or await detect_group(client)
        print(f"📂 group: {group}")

        # List-only mode — แสดง courses แล้วจบ
        if args.list_only:
            print(f"\n📚 Listing courses ใน group {group}...")
            courses = await list_courses_in_group(client, group)
            print(f"\nเจอ {len(courses)} courses:")
            for c in courses:
                print(f"  {c['id']:>6}  {c.get('code', ''):<14} {c.get('title', '')[:60]}")
            return

        new_count = 0
        for cid in args.courses:
            try:
                new_qs = await dump_one_course(
                    client, str(cid),
                    group=group,
                    repeat=args.repeat,
                    smart=args.smart,
                    smart_patience=args.smart_patience,
                    max_repeat=args.max_repeat,
                )
                for q in new_qs:
                    if q["q_hash"] not in existing:
                        existing[q["q_hash"]] = q
                        new_count += 1
                    else:
                        # keep existing user-edited correct_value
                        old = existing[q["q_hash"]]
                        if old.get("correct_value") is None and old.get("correct_index") is None:
                            existing[q["q_hash"]] = {**q, "notes": old.get("notes", "")}
            except KeyboardInterrupt:
                print(f"\n⏭️  หยุดที่ course {cid}")
                break
            except Exception as e:
                print(f"❌ course {cid} error: {e}")
                continue

    # Save
    questions = list(existing.values())
    questions.sort(key=lambda x: (x.get("course_id", ""), x.get("exam_type", ""), x["q_hash"]))
    data = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(questions),
        "filled": sum(1 for q in questions if q.get("correct_value") or q.get("correct_index") is not None),
        "questions": questions,
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'═' * 60}")
    print(f"💾 save → {out_path}")
    print(f"   รวม {len(questions)} ข้อ ({new_count} ใหม่)")
    print(f"   มี correct_value แล้ว: {data['filled']}/{len(questions)}")
    print(f"\n📝 ขั้นตอนต่อไป:")
    print(f"   1. เปิด {out_path} ใส่ correct_value หรือ correct_index")
    print(f"   2. python scripts/import_answers.py {out_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹  ยกเลิก")
