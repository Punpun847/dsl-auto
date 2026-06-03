"""Smart submit — per-user course selection

สำหรับแต่ละ user:
  1. Login → fetch_courses (กรองคอร์สที่ผ่านแล้วออก)
  2. เลือกชั่วโมงตามที่ระบุใน accounts.csv (column 3, บังคับ)
  3. Submit job ผ่าน API
"""
import asyncio
import csv
import json
import logging
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from app.worker.dsl_client import DSLClient

API_BASE = "http://127.0.0.1:8000"


async def get_incomplete(nid: str, pwd: str) -> list[dict]:
    """Login + fetch incomplete courses"""
    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        if not ok:
            return []
        courses = await client.fetch_courses()
        return courses


def pick_courses(courses: list[dict], target_hours: float) -> tuple[list[str], float]:
    """เลือก courses ให้ครบ target_hours — เรียง hours มาก→น้อย (ใหญ่ก่อน)
    คอร์สที่ใหญ่เกิน cap จะถูก skip (ไม่ break) เพื่อให้คอร์สเล็กกว่าได้รับการพิจารณา"""
    sorted_c = sorted(courses, key=lambda c: float(c.get("hours") or 1), reverse=True)
    picked = []
    total_hr = 0.0
    max_hours = target_hours
    for c in sorted_c:
        if total_hr >= target_hours:
            break
        h = float(c.get("hours") or 1)
        if total_hr + h > max_hours:
            continue
        picked.append(str(c["id"]))
        total_hr += h
    return picked, total_hr


def submit_job(nid: str, pwd: str, course_ids: list[str], target_hours: float) -> tuple[bool, str]:
    """Submit ผ่าน API พร้อม retry + backoff (เฉพาะ network err / 5xx / 429)"""
    BACKOFFS = [2, 5, 10, 20]
    last_err = "unknown"
    for attempt in range(len(BACKOFFS) + 1):
        try:
            r = httpx.post(
                f"{API_BASE}/jobs/",
                data={
                    "nid": nid,
                    "pwd": pwd,
                    "courses": json.dumps(course_ids),
                    "total_price": "0",
                    "total_hours": str(target_hours),
                },
                timeout=30,
            )
            if r.status_code == 201:
                return True, r.json().get("id", "")
            last_err = f"HTTP {r.status_code} — {r.text[:100]}"
            # 4xx (ยกเว้น 429) = invalid input — retry เท่าไหร่ก็เหมือนเดิม
            if 400 <= r.status_code < 500 and r.status_code != 429:
                return False, last_err
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < len(BACKOFFS):
            time.sleep(BACKOFFS[attempt])
    return False, last_err


async def main():
    csv_path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "accounts.csv")
    rows = []
    skipped = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if len(row) < 3 or not row[2].strip():
                skipped.append(f"  บรรทัด {lineno}: ไม่มี column ชั่วโมง — ข้าม")
                continue
            try:
                hours = float(row[2].strip())
            except ValueError:
                skipped.append(f"  บรรทัด {lineno}: ชั่วโมง '{row[2].strip()}' ไม่ใช่ตัวเลข — ข้าม")
                continue
            rows.append((row[0].strip(), row[1].strip(), hours))

    if skipped:
        print("⚠️  บรรทัดที่ไม่มีชั่วโมง (ถูกข้าม):")
        for s in skipped:
            print(s)
        print()

    print(f"📋 {len(rows)} users\n")

    results = []
    out_file = ROOT / "smart_jobs.csv"
    with open(out_file, "w", encoding="utf-8") as f_out:
        for i, (nid, pwd, target_hours) in enumerate(rows, 1):
            label = f"{nid[:4]}***{nid[-3:]}"
            print(f"[{i}/{len(rows)}] {label}  (เป้า {target_hours:.0f} ชม.)", flush=True)
            print(f"  🔑 Login + fetch_courses...", flush=True)
            courses = await get_incomplete(nid, pwd)
            print(f"  📚 incomplete: {len(courses)} คอร์ส", flush=True)
            if not courses:
                print(f"  ❌ ไม่มีคอร์สที่ทำได้")
                continue
            picked, total_hr = pick_courses(courses, target_hours)
            print(f"  🎯 เลือก {len(picked)} คอร์ส = {total_hr:.1f} ชม.")
            print(f"  📤 submit job...", flush=True)
            ok, result = submit_job(nid, pwd, picked, target_hours)
            if ok:
                print(f"  ✅ job_id: {result[:8]}...")
                f_out.write(f"{nid},{result}\n")
                f_out.flush()
                results.append((nid, result, picked))
            else:
                print(f"  ❌ {result}")

    print(f"\n💾 บันทึก {len(results)} jobs → {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
