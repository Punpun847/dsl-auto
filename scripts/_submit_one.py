"""Submit job สำหรับ user คนเดียว โดย fetch courses จาก SET ก่อน

Usage:
    python scripts/_submit_one.py <NID> <PWD>
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))
sys.stdout.reconfigure(encoding="utf-8")

from scripts.smart_submit import get_incomplete, pick_courses, submit_job

async def main():
    if len(sys.argv) < 4:
        print("Usage: python scripts/_submit_one.py <NID> <PWD> <HOURS>")
        sys.exit(1)

    nid = sys.argv[1]
    pwd = sys.argv[2]
    try:
        target_hours = float(sys.argv[3])
    except ValueError:
        print(f"❌ HOURS ต้องเป็นตัวเลข ได้รับ: {sys.argv[3]}")
        sys.exit(1)
    label = f"{nid[:4]}***{nid[-3:]}"

    print(f"🔑 [{label}] Login + fetch_courses...")
    courses = await get_incomplete(nid, pwd)
    if not courses:
        print("❌ ไม่มีคอร์สที่ทำได้")
        return

    print(f"📚 incomplete: {len(courses)} คอร์ส")
    picked, total_hr = pick_courses(courses, target_hours)
    print(f"🎯 เลือก {len(picked)} คอร์ส = {total_hr:.1f} ชม.")
    print(f"   {picked}")

    ok, result = submit_job(nid, pwd, picked, target_hours)
    if ok:
        print(f"✅ job submitted: {result[:8]}...")
        print(f"   job_id: {result}")
    else:
        print(f"❌ submit ล้มเหลว: {result}")


if __name__ == "__main__":
    asyncio.run(main())
