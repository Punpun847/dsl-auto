"""Debug fetch_courses end-to-end ด้วย credentials จริง

Usage:
    python scripts/debug_fetch_courses.py <NID> <PWD>

Output:
    {tmp}/gyso_dsl/
        dsl_01_login_loaded.png
        dsl_02_filled.png
        ...
        dsl_06_page_N.png
        scraped_courses.json     ← raw card data ทุก course
        filter_status_map.json   ← API response (enroll_id, pct, cert) ทุก course

ใช้เมื่อ:
    - user รายงานว่า "courses ไม่ครบ"
    - course ที่ทำแล้ว ยังโผล่ในรายการ (false-negative ของ certificate detection)
    - course ที่ยังไม่ทำ ไม่ขึ้นในรายการ (false-positive)
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ติด DEBUG mode ก่อน import dsl_client
os.environ["DSL_DEBUG"] = "1"

# logging.DEBUG เพื่อดู debug logs ของ filter
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# silence verbose
for noisy in ("asyncio", "urllib3", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Make sure project root + stubs are on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))


async def main(nid: str, pwd: str) -> None:
    from app.worker.dsl_client import DSLClient, SHOT_DIR

    print(f"🔧 debug mode: screenshots + JSON dumps จะ save ที่ {SHOT_DIR}")
    print(f"📂 อ่าน {SHOT_DIR}/scraped_courses.json + filter_status_map.json หลังจบ")
    print()

    async with DSLClient(headless=False) as client:
        print("🔑 logging in...")
        if not await client.login(nid, pwd):
            print(f"❌ login failed: {client.last_error}")
            return
        print("✅ logged in")

        print()
        print("📚 fetching courses (with full debug)...")
        courses = await client.fetch_courses()

        print()
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"✨ ส่งกลับ {len(courses)} courses")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Group by status
        by_status = {}
        for c in courses:
            s = c.get("status", "?")
            by_status.setdefault(s, []).append(c)
        for status, items in by_status.items():
            print(f"\n  [{status}] {len(items)} courses:")
            for c in items[:10]:
                hint = " ⚠️ HTML-hint=complete" if c.get("card_completed_hint") else ""
                print(f"    • {c.get('code', '?')} {c.get('title', '')[:50]:<50} "
                      f"{c.get('hours', 0):.1f}h ฿{c.get('price', 0)}{hint}")
            if len(items) > 10:
                print(f"    ... +{len(items)-10} more")

        # Save final result
        out = Path(SHOT_DIR) / "final_courses.json"
        out.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n💾 saved → {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/debug_fetch_courses.py <NID> <PWD>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
