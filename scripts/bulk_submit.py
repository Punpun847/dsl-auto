"""ส่งงาน automation หลายคนพร้อมกัน — อ่านจาก CSV แล้ว POST /jobs/ ทุกคน

Usage:
    python scripts/bulk_submit.py accounts.csv

Format ของ accounts.csv (ไม่มี header):
    1234567890123,password1
    9876543210987,password2

คอร์สที่รัน: WMD series 6 คอร์ส (มีเฉลยใน cache ครบแล้ว)
    กำหนดได้ใน COURSE_IDS ด้านล่าง

ผลลัพธ์:
    ✅ 1234*** → job_id: abc123
    ❌ 9876*** → HTTP 503 ระบบบอทปิดอยู่
"""
import csv
import sys
import time
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────
API_BASE    = "http://127.0.0.1:8000"
COURSE_IDS  = ["1905", "1906", "1907", "1937", "1938", "1960"]   # WMD series
TOTAL_HOURS = "3"
DELAY_SEC   = 2    # หน่วงระหว่าง job กัน server overload
# ──────────────────────────────────────────────────────────


def submit_job(nid: str, pwd: str) -> tuple[bool, str]:
    try:
        r = httpx.post(
            f"{API_BASE}/jobs/",
            data={
                "nid": nid,
                "pwd": pwd,
                "courses": str(COURSE_IDS).replace("'", '"'),
                "total_price": "0",
                "total_hours": TOTAL_HOURS,
            },
            timeout=30,
        )
        if r.status_code == 201:
            job_id = r.json().get("id", "?")
            return True, f"job_id: {job_id}"
        return False, f"HTTP {r.status_code} — {r.text[:120]}"
    except Exception as e:
        return False, str(e)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/bulk_submit.py accounts.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"❌ ไม่พบไฟล์ {csv_path}")
        sys.exit(1)

    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                rows.append((row[0].strip(), row[1].strip()))

    print(f"📋 {len(rows)} accounts | คอร์ส: {COURSE_IDS}")
    print(f"🌐 API: {API_BASE}\n")

    ok_list, fail_list = [], []
    for i, (nid, pwd) in enumerate(rows, 1):
        label = f"{nid[:4]}***{nid[-3:]}"
        print(f"[{i}/{len(rows)}] {label} ...", end=" ", flush=True)
        success, msg = submit_job(nid, pwd)
        if success:
            print(f"✅ {msg}")
            ok_list.append((nid, msg))
        else:
            print(f"❌ {msg}")
            fail_list.append((nid, msg))
        if i < len(rows):
            time.sleep(DELAY_SEC)

    print(f"\n{'═'*55}")
    print(f"✅ ส่งสำเร็จ : {len(ok_list)}/{len(rows)}")
    print(f"❌ ล้มเหลว  : {len(fail_list)}/{len(rows)}")
    if fail_list:
        print("\nรายการที่ล้มเหลว:")
        for nid, reason in fail_list:
            print(f"  {nid} → {reason}")

    # บันทึก job_ids ไว้สำหรับ bulk_download.py
    jobs_file = csv_path.parent / "jobs.csv"
    with open(jobs_file, "w", encoding="utf-8") as f:
        for nid, msg in ok_list:
            job_id = msg.replace("job_id: ", "").strip()
            f.write(f"{nid},{job_id}\n")
    print(f"\n💾 บันทึก job IDs → {jobs_file}")


if __name__ == "__main__":
    main()
