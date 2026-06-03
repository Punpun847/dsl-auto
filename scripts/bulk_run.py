"""Batch automation — ส่งงานครั้งละ 5 คน รอเสร็จ แล้วโหลด PDF รวม

Usage:
    python scripts/bulk_run.py accounts.csv

Config:
    BATCH_SIZE  — จำนวนคนต่อรอบ (default 5)
    COURSE_IDS  — คอร์สที่รัน
    POLL_SEC    — ตรวจสถานะทุกกี่วินาที
    TIMEOUT_MIN — รอสูงสุดกี่นาทีต่อ batch

accounts.csv (ไม่มี header):
    1234567890123,password1
    9876543210987,password2
    ...

ผลลัพธ์:
    certs/1234567890123.pdf  ← ทุก cert ของคนนี้รวมใน PDF เดียว
    certs/9876543210987.pdf
    ...
"""
import csv
import sys
import time
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────
API_BASE    = "http://127.0.0.1:8000"
COURSE_IDS  = [
    # 18 courses × 1 hr = 18 ชั่วโมง SET certified
    "666",   # ภัยทางการเงิน
    "668",   # พฤติกรรมการเงิน
    "667",   # Digital Financial Literacy
    "665",   # การวางแผนการเงิน
    "606",   # ออมเงิน
    "607",   # บัตรเครดิต
    "605",   # เตรียมตัวทำงาน
    "604",   # มนุษย์เงินเดือน
    "603",   # อาชีพยุคใหม่
    "925",   # Work-Life Integration
    "926",   # คนเจนใหม่
    "615",   # Stock Screening
    "614",   # Sector Rotation
    "613",   # Sector Analysis
    "952",   # Finance for Starting Business
    "1287",  # ครบเครื่องเรื่องลงทุน
    "1296",  # Customer Validation
    "1055",  # อาชีพ Passion
]
TOTAL_HOURS = "3"
BATCH_SIZE  = 12      # ส่งหมดทุกคน → workers ดึงคิวเอง (4 parallel)
POLL_SEC    = 20
TIMEOUT_MIN = 90      # เผื่อ batch ใหญ่ queue ยาว
OUT_DIR     = Path("certs")
# ──────────────────────────────────────────────────────────

DONE_STATUSES = {"done", "failed", "error"}


def submit_job(nid: str, pwd: str) -> tuple[bool, str]:
    """Submit job ลอง 5 ครั้ง ถ้าเจอ 503 (workers busy)"""
    last_err = ""
    for attempt in range(5):
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
                return True, r.json().get("id", "")
            if r.status_code == 503:
                # workers busy → retry
                last_err = f"HTTP 503 (retry {attempt+1}/5)"
                time.sleep(3 + attempt * 2)
                continue
            return False, f"HTTP {r.status_code} — {r.text[:100]}"
        except Exception as e:
            last_err = str(e)
            time.sleep(2)
    return False, last_err


def get_status(job_id: str) -> str:
    try:
        r = httpx.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
        if r.status_code == 200:
            return r.json().get("status", "unknown")
        return "error"
    except Exception:
        return "error"


def download_bundle(nid: str, job_id: str) -> tuple[bool, str]:
    try:
        r = httpx.get(f"{API_BASE}/jobs/{job_id}/certificates/bundle", timeout=60)
        if r.status_code == 200:
            out_path = OUT_DIR / f"{nid}.pdf"
            out_path.write_bytes(r.content)
            size_kb = len(r.content) // 1024
            return True, f"{size_kb} KB"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def wait_batch(batch: list[tuple[str, str]]) -> dict[str, str]:
    """รอ jobs ใน batch เสร็จ คืน {job_id: status}"""
    job_ids = {job_id for _, job_id in batch}
    results = {}
    deadline = time.time() + TIMEOUT_MIN * 60

    while job_ids and time.time() < deadline:
        time.sleep(POLL_SEC)
        done_now = set()
        for job_id in job_ids:
            status = get_status(job_id)
            if status in DONE_STATUSES:
                results[job_id] = status
                done_now.add(job_id)
        job_ids -= done_now
        if job_ids:
            print(f"    ⏳ รออีก {len(job_ids)} jobs...", flush=True)

    # timeout — mark remaining as timeout
    for job_id in job_ids:
        results[job_id] = "timeout"
    return results


def process_batch(batch_rows: list[tuple[str, str]], batch_num: int, total_batches: int):
    print(f"\n{'═'*60}")
    print(f"  Batch {batch_num}/{total_batches} — {len(batch_rows)} คน")
    print(f"{'═'*60}")

    # 1. Submit
    submitted = []
    for nid, pwd in batch_rows:
        label = f"{nid[:4]}***{nid[-3:]}"
        ok, result = submit_job(nid, pwd)
        if ok:
            print(f"  ✅ {label} → job: {result[:8]}...")
            submitted.append((nid, result))
        else:
            print(f"  ❌ {label} → {result}")

    if not submitted:
        print("  ⚠️  ไม่มี job ที่ submit สำเร็จ")
        return

    # 2. รอเสร็จ
    print(f"\n  ⏳ รอ {len(submitted)} jobs (poll ทุก {POLL_SEC}s, timeout {TIMEOUT_MIN}m)...")
    statuses = wait_batch(submitted)

    # 3. Download PDF
    print()
    for nid, job_id in submitted:
        label = f"{nid[:4]}***{nid[-3:]}"
        st = statuses.get(job_id, "?")
        if st == "done":
            ok, msg = download_bundle(nid, job_id)
            if ok:
                print(f"  📄 {label} → certs/{nid}.pdf ({msg})")
            else:
                print(f"  ⚠️  {label} → done แต่โหลด PDF ไม่ได้: {msg}")
        elif st == "failed":
            print(f"  ❌ {label} → งานล้มเหลว (ดู log Celery)")
        elif st == "timeout":
            print(f"  ⏰ {label} → timeout {TIMEOUT_MIN}m (งานยังวิ่งอยู่)")
        else:
            print(f"  ❓ {label} → status={st}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/bulk_run.py accounts.csv")
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

    OUT_DIR.mkdir(exist_ok=True)
    total = len(rows)
    batches = [rows[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    print(f"📋 {total} accounts | {len(batches)} batches × {BATCH_SIZE} คน")
    print(f"📁 PDF → {OUT_DIR.resolve()}")
    print(f"🎓 คอร์ส: {COURSE_IDS}")

    for i, batch in enumerate(batches, 1):
        process_batch(batch, i, len(batches))

    print(f"\n{'═'*60}")
    print(f"✅ เสร็จสิ้น — ดู PDF ใน {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
