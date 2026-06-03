"""ทดสอบว่า answer_bank cache ทำงานจริง — submit exam ด้วย cache แทน Gemini/random

Flow:
  1. Login SET-direct
  2. Enroll + mark topics ของ course
  3. Call _submit_exam ทั้ง pre-test, post-test, exam (ใช้ cache lookup)
  4. ดู score + check certificate_datetime

ถ้า cache hit ครบ → คะแนนน่าจะ 100% → cert ออก

Usage:
    python scripts/test_exam_with_cache.py <email> <pwd> 1905
    python scripts/test_exam_with_cache.py <email> <pwd> 1905 --headed     # เห็น browser
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))

os.environ["DSL_DEBUG"] = "0"

# Monkey-patch SET_BASE → SETGroup (course 1905 อยู่ใน SETGroup ไม่ใช่ SETStudentLoan)
import app.worker.dsl_client as dsl_mod
dsl_mod.SET_BASE = "https://elearning.set.or.th/SETGroup"

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
for noisy in ("asyncio", "urllib3", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from app.worker.dsl_client import DSLClient


async def ensure_topics_complete(client, enroll_id):
    """Mark ทุก topic ให้ complete (ปลดล็อก exam)"""
    enroll_data = await client.page.evaluate(f"""async () => {{
        const r = await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}});
        return r.json();
    }}""")
    topics = []
    def _extract(nodes):
        for n in (nodes or []):
            ch = n.get("parent", [])
            if isinstance(ch, list) and ch:
                _extract(ch)
            else:
                e2t = n.get("enroll2topic") or {}
                topics.append({"id": n["id"], "e2t_id": e2t.get("id"),
                              "pct": int(n.get("percentage") or 0)})
    _extract(enroll_data.get("topics") or [])

    incomplete = [t for t in topics if t["pct"] < 100]
    if not incomplete:
        print(f"  ✅ topics ครบแล้ว ({len(topics)} ข้อ)")
        return

    print(f"  🔧 marking {len(incomplete)}/{len(topics)} topics...")
    for t in incomplete:
        tid, e2t_id = t["id"], t["e2t_id"]
        if not e2t_id:
            await client.page.evaluate(f"""async () => {{
                const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                await fetch('/api/site/enroll2topic_stage', {{
                    method:'POST', headers:h, credentials:'include',
                    body:'enroll={enroll_id}&topics={tid}',
                }});
            }}""")
        await client.page.evaluate(f"""async () => {{
            const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
            await fetch('/api/site/enroll/views', {{
                method:'POST', headers:h, credentials:'include',
                body:'id=&enroll_id={enroll_id}&topics_id={tid}&state=vod',
            }});
        }}""")
        if not e2t_id:
            refetch = await client.page.evaluate(
                f"""async () => (await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}})).json()"""
            )
            def find(nodes):
                for n in (nodes or []):
                    if isinstance(n.get('parent'), list) and n.get('parent'):
                        r = find(n['parent'])
                        if r: return r
                    elif n.get('id') == tid:
                        return (n.get('enroll2topic') or {}).get('id')
                return None
            e2t_id = find(refetch.get('topics') or [])
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
    print(f"  ✅ topics marked")


async def test_one_course(client, course_id: str, group: str):
    """ทดสอบ course เดียว — คืน dict ผลลัพธ์"""
    print(f"\n{'═' * 60}")
    print(f"🎯 Course {course_id}")
    print(f"{'═' * 60}")

    course_api = f"/api/site/groups/{group}/courses/{course_id}"
    info = await client.page.evaluate(f"""async () => {{
        const r = await fetch('{course_api}',
            {{credentials:'include', headers:{{'X-Requested-With':'XMLHttpRequest'}}}});
        return r.ok ? r.json() : null;
    }}""")
    if not info:
        return {"course_id": course_id, "status": "course_not_found"}

    title = info.get("title", course_id)
    eid = info.get("enroll_id")
    print(f"📚 {title}")

    # Enroll ถ้ายังไม่ลง
    if not eid:
        print(f"📝 enrolling...")
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
        info = await client.page.evaluate(f"""async () => {{
            const r = await fetch('{course_api}', {{credentials:'include'}});
            return r.json();
        }}""")
        eid = info.get("enroll_id")

    if not eid:
        return {"course_id": course_id, "title": title, "status": "enroll_fail"}

    # Mark topics + submit exams
    await ensure_topics_complete(client, eid)
    await client._submit_exam(eid, "pre-test")
    await client._submit_exam(eid, "post-test")
    await client._submit_exam(eid, "exam")

    # Check status
    check = await client.page.evaluate(f"""async () => {{
        const r = await fetch('/api/site/enroll/{eid}', {{credentials:'include'}});
        return r.json();
    }}""")

    return {
        "course_id": course_id,
        "title": title,
        "enroll_id": eid,
        "learning_pct": check.get("learning_percentage"),
        "post_test_pct": check.get("post_test_percentage"),
        "exam_pct": check.get("exam_percentage"),
        "certificate_datetime": check.get("certificate_datetime"),
        "certificate_ref": check.get("certificate_reference_number"),
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("pwd")
    parser.add_argument("course_ids", nargs="+", help="1+ course IDs to test")
    parser.add_argument("--group", default="SETGroup")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    dsl_mod.SET_BASE = f"https://elearning.set.or.th/{args.group}"
    print(f"🌐 SET_BASE patched → {dsl_mod.SET_BASE}")

    import redis as sync_redis
    from app.config import settings
    r = sync_redis.from_url(settings.redis_url, decode_responses=True)
    cache_size = r.hlen("dsl:answer_cache")
    print(f"📋 answer_bank: {cache_size} ข้อ")
    print()

    async with DSLClient(headless=not args.headed) as client:
        print(f"🔑 Login SET-direct...")
        if not await client.login_set(args.email, args.pwd):
            print(f"❌ login fail: {client.last_error}")
            return
        print(f"✅ Login OK")

        results = []
        for cid in args.course_ids:
            try:
                result = await test_one_course(client, str(cid), args.group)
                results.append(result)
            except Exception as e:
                print(f"❌ course {cid} error: {e}")
                results.append({"course_id": cid, "status": "error", "error": str(e)})

        # Final summary table
        print(f"\n\n{'═' * 70}")
        print(f"📊 SUMMARY ({len(results)} courses)")
        print(f"{'═' * 70}")
        print(f"  {'Course':<8} {'Title':<35} {'Learn':>6} {'Post':>6} {'Cert?':>8}")
        print(f"  {'-' * 8} {'-' * 35} {'-' * 6} {'-' * 6} {'-' * 8}")
        for r2 in results:
            title = (r2.get("title") or "")[:33]
            learn = f"{r2.get('learning_pct', '-')}"
            post = f"{r2.get('post_test_pct', '-')}"
            cert = "✅" if r2.get("certificate_datetime") else ("REF" if r2.get("certificate_ref") else "-")
            print(f"  {r2.get('course_id'):<8} {title:<35} {learn:>6} {post:>6} {cert:>8}")
        print(f"{'═' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
