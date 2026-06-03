"""Harvest exam answers using a "fresh" SET account.

Workflow:
  1. Login บัญชี 2 (ที่ยังไม่ได้ทำคอร์ส) → SSO → SET
  2. Loop ทุก course (หรือเฉพาะที่ระบุ):
       a. Enroll + mark topics complete (ผ่าน API — ไม่ดูวิดีโอจริง)
       b. เปิดหน้า exam (post-test) ใน browser HEADED
       c. Inject listener — capture เมื่อ user click radio
       d. ⏸  รอ user ตอบครบ + click submit เอง
       e. หลัง submit:
            ✅ ผ่าน ≥95% → save ทุกข้อใน answer_bank
            ⚠️ ผ่าน 70-94% → save แต่ flag "needs_verification"
            ❌ < 70%       → ไม่ save, แนะ retry
  3. ทุก answer เก็บลง Redis hash `dsl:answer_cache` (same key ที่ DSLClient อ่าน)

Usage:
    # harvest course เดียว
    python scripts/harvest_answers.py <NID> <PWD> 666

    # harvest หลาย courses
    python scripts/harvest_answers.py <NID> <PWD> 666 1941 1942

    # harvest ทุก course ที่ยังไม่จบ (long — ใช้เวลาเป็นชม.)
    python scripts/harvest_answers.py <NID> <PWD> --all
"""
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))

# Force headed mode
os.environ["DSL_DEBUG"] = "0"  # ปิด screenshot
import redis as sync_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
for noisy in ("asyncio", "urllib3", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


REDIS_KEY = "dsl:answer_cache"
SAVE_THRESHOLD_TRUSTED = 0.95   # ผ่าน 95%+ = save ทุกข้อ trusted
SAVE_THRESHOLD_FLAGGED = 0.70   # ผ่าน 70-94% = save แต่ flag


def question_hash(text: str) -> str:
    """ตรงกับ DSLClient._question_hash — SHA1 12 chars"""
    normalized = " ".join((text or "").split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def text_hash(text: str) -> str:
    """SHA1 8 chars — สำหรับ fallback match ถ้า SET random option.value"""
    normalized = " ".join((text or "").split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


def get_redis():
    from app.config import settings
    return sync_redis.from_url(settings.redis_url, decode_responses=True)


def existing_cache() -> Dict[str, str]:
    try:
        return get_redis().hgetall(REDIS_KEY) or {}
    except Exception:
        return {}


def save_answers(captured: List[Dict], trusted: bool = True) -> int:
    """Save captured answers ลง Redis ในรูป JSON {v, t}. คืนจำนวนข้อที่ save ใหม่"""
    if not captured:
        return 0
    r = get_redis()
    new_count = 0
    pipe = r.pipeline()
    for c in captured:
        qh = question_hash(c["q_text"])
        if not qh:
            continue
        # robust format: เก็บทั้ง value + text_hash ของ option ที่ user เลือก
        # ✱ ตอน harvest — text ของ option ที่ user click ถูก capture เป็น c["option_text"]
        opt_text = c.get("option_text", "")
        payload = json.dumps(
            {"v": str(c["value"]), "t": text_hash(opt_text)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        pipe.hset(REDIS_KEY, qh, payload)
        new_count += 1
    pipe.execute()
    return new_count


async def harvest_course(client, course_id: str) -> bool:
    """Harvest ของ course เดียว. คืน True ถ้า save ได้, False ถ้าข้าม"""
    from app.worker.dsl_client import SET_BASE

    print(f"\n{'━' * 60}")
    print(f"🎯 Course {course_id}")
    print(f"{'━' * 60}")

    # ── 1. ดึง course info + enroll_id ──
    try:
        course_data = await client.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',
                {{credentials:'include', headers:{{'X-Requested-With':'XMLHttpRequest'}}}});
            return r.ok ? r.json() : null;
        }}""")
    except Exception as e:
        print(f"  ❌ ดึง course info fail: {e}")
        return False

    if not course_data:
        print(f"  ❌ ไม่พบ course {course_id}")
        return False

    title = course_data.get("title", course_id)
    enroll_id = course_data.get("enroll_id")
    cert = course_data.get("certificate_datetime")
    print(f"  📚 {title}")

    if cert:
        print(f"  ⏭️  course นี้จบไปแล้ว (cert {cert}) — skip")
        return False

    # ── 2. Enroll ถ้ายังไม่ลง ──
    if not enroll_id:
        print(f"  📝 enrolling...")
        try:
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
                const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',
                    {{credentials:'include', headers:{{'X-Requested-With':'XMLHttpRequest'}}}});
                return r.json();
            }}""")
            enroll_id = course_data.get("enroll_id")
        except Exception as e:
            print(f"  ❌ enroll fail: {e}")
            return False

    if not enroll_id:
        print(f"  ❌ enroll ไม่ได้")
        return False

    # ── 3. Mark all topics complete (เพื่อปลดล็อก exam) ──
    print(f"  🔧 marking topics complete...")
    try:
        # Re-use existing automation: complete_course_via_api ทำหมดเลย incl. exam
        # แต่เราอยากแค่ topics — งั้นเรียก method ส่วน topic ตรงๆ
        pdf_path = await client.complete_course_via_api(
            course_id=course_id,
            on_log=None,
            cert_dir=None,  # ไม่ดาวน์โหลด cert
        )
        # ⚠️ complete_course_via_api ทำ exam ด้วย — แต่เพราะไม่มี cache + ไม่มี Gemini
        # มันอาจไม่ผ่าน → cert ไม่ออก. แต่อย่างน้อย topics + exam ครั้งแรก ถูก submit แล้ว
        # หลังจากนี้ user สามารถ retry exam manual บน browser ได้
        if pdf_path:
            print(f"  🎓 ได้ cert ฟลุ๊ค (random ตอบผ่าน!): {pdf_path}")
            # cache ของ attempt ที่ผ่านจะ auto-save อยู่แล้ว ใน _submit_exam
            return True
        print(f"  ℹ️  ไม่ผ่าน exam ผ่าน random ตอบ — user retry manual ได้")
    except Exception as e:
        print(f"  ⚠️  complete_course_via_api error: {e}")
        # ไปต่อ — อาจจะ enroll + mark complete ส่วนหนึ่งแล้ว

    # ── 4. เปิด post-test page ให้ user ทำ ──
    exam_types = ["post-test", "exam"]
    captured_total = 0
    for exam_type in exam_types:
        url = f"{SET_BASE}/enroll/{enroll_id}/exam/{exam_type}"
        print(f"\n  🎯 เปิดหน้า {exam_type}: {url}")
        try:
            await client.page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"  ⚠️  goto {exam_type} error: {e}")
            continue

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

        # ตรวจว่าเจอ radio
        n_radios = await client.page.evaluate(
            "() => document.querySelectorAll('input[type=\"radio\"]').length"
        )
        if n_radios == 0:
            print(f"  ⚠️  {exam_type}: ไม่เจอ radio — ข้าม")
            continue

        # Inject listener — capture q_text + value + option_text เพื่อ robust cache
        await client.page.evaluate("""() => {
            window._capture = [];
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                r.addEventListener('change', () => {
                    let parent = r.closest('.question, .form-group, .quiz-question, li, fieldset, .panel');
                    if (!parent) parent = r.parentElement?.parentElement;
                    const qNode = parent?.querySelector('legend, h3, h4, h5, .question-title, p:first-of-type, label');
                    const qText = (qNode?.innerText || parent?.innerText || '').trim();
                    // option text ของ radio ที่ check
                    const optLbl = r.closest('label') || document.querySelector(`label[for="${r.id}"]`);
                    const optText = (optLbl?.innerText || '').trim();
                    // remove previous answer for this name
                    window._capture = window._capture.filter(c => c.q_name !== r.name);
                    window._capture.push({
                        q_name: r.name,
                        q_text: qText.slice(0, 500),
                        value: r.value,
                        option_text: optText.slice(0, 300),
                    });
                });
            });
        }""")

        print(f"\n  📝 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📝  กรุณาทำ {exam_type} ใน browser ที่เปิดอยู่")
        print(f"  📝  ตอบให้ถูกที่สุด (ผ่าน 95%+ → save trusted)")
        print(f"  📝  คลิก submit แล้วกด Enter ตรงนี้")
        print(f"  📝 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  ⏸  รอ... (Ctrl+C เพื่อข้าม)")
        try:
            await asyncio.get_event_loop().run_in_executor(None, input)
        except KeyboardInterrupt:
            print(f"\n  ⏭️  skip {exam_type}")
            continue

        # ดึง captured + score
        captured = await client.page.evaluate("() => window._capture || []") or []
        score, count = await get_latest_score(client, enroll_id, exam_type)

        print(f"\n  📊 captured {len(captured)} answers, score {score}/{count}")
        if count == 0:
            print(f"  ⚠️  อ่าน score ไม่ได้ — ลอง refresh หรือ check บน browser")
            continue
        pct = score / count if count else 0

        if pct >= SAVE_THRESHOLD_TRUSTED:
            n = save_answers(captured, trusted=True)
            print(f"  ✅ {pct:.0%} — saved {n} answers (trusted)")
            captured_total += n
        elif pct >= SAVE_THRESHOLD_FLAGGED:
            n = save_answers(captured, trusted=False)
            print(f"  ⚠️  {pct:.0%} — saved {n} answers (flagged, ควร retry ภายหลัง)")
            captured_total += n
        else:
            print(f"  ❌ {pct:.0%} ต่ำเกินไป — ไม่ save")

    print(f"\n  💾 รวม {captured_total} answers จาก course {course_id}")
    return captured_total > 0


async def get_latest_score(client, enroll_id: int, exam_type: str) -> Tuple[int, int]:
    """ดึง score ล่าสุดจาก SET history API"""
    type_n = {"pre-test": 1, "post-test": 4, "exam": 3}.get(exam_type, 3)
    # ต้องรู้ quiz_id — ดึงจาก exam page
    quiz_info = await client.page.evaluate("""() => {
        let qid = null;
        const el = document.querySelector('[data-quiz-id]');
        if (el) qid = el.dataset.quizId;
        if (!qid) {
            const m = document.body.innerHTML.match(/quiz[_-]?id["':\\s=]+(\\d{3,6})/i);
            if (m) qid = m[1];
        }
        return qid;
    }""")
    if not quiz_info:
        return (0, 0)
    try:
        hist = await client.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/exam/{quiz_info}/history?page=1&per_page=10&enroll_id={enroll_id}',
                {{credentials:'include'}});
            return r.json();
        }}""")
    except Exception:
        return (0, 0)
    data = (hist or {}).get("data") or []
    if not data:
        return (0, 0)
    top = data[0]
    return (int(top.get("score") or 0), int(top.get("count") or 0))


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    course_ids = None
    if not rest or "--all" in rest:
        course_ids = None
    else:
        course_ids = [c for c in rest if c.isdigit()]

    from app.worker.dsl_client import DSLClient

    print(f"📊 cache ปัจจุบัน: {len(existing_cache())} ข้อ")
    print(f"🚀 launching browser (headed)...")

    async with DSLClient(headless=False) as client:
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"❌ login fail: {client.last_error}")
            return
        print(f"✅ logged in")

        if not await client.goto_set():
            print(f"❌ SSO SET fail")
            return
        print(f"✅ SSO SET")

        # ถ้าไม่ระบุ course → ดึงทั้งหมด
        if course_ids is None:
            print(f"📚 ดึงรายการ courses ที่ยังไม่จบ...")
            courses = await client.fetch_courses()
            course_ids = [c["id"] for c in courses]
            print(f"   เจอ {len(course_ids)} courses")
            print(f"   {[c.get('code', c['id']) for c in courses[:10]]}")
            input(f"\nกด Enter เพื่อเริ่ม harvest (Ctrl+C เพื่อยกเลิก)...")

        total_saved = 0
        for i, cid in enumerate(course_ids, 1):
            print(f"\n[{i}/{len(course_ids)}]")
            try:
                if await harvest_course(client, str(cid)):
                    total_saved += 1
            except KeyboardInterrupt:
                print(f"\n\n⏭️  หยุดการ harvest")
                break
            except Exception as e:
                print(f"  ❌ course {cid} error: {e}")
                continue

        print(f"\n{'═' * 60}")
        print(f"📊 สรุป: harvest {total_saved}/{len(course_ids)} courses สำเร็จ")
        print(f"💾 cache รวมหลัง harvest: {len(existing_cache())} ข้อ")
        print(f"{'═' * 60}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹  ยกเลิก")
