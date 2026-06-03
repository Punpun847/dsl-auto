"""ดาวน์โหลด PDF วุฒิบัตรทุกคนจาก jobs.csv (output ของ bulk_submit.py)

Usage:
    python scripts/bulk_download.py jobs.csv

ผลลัพธ์:
    certs/1234567890123.pdf
    certs/9876543210987.pdf
    ...
"""
import csv
import sys
import time
from pathlib import Path

import httpx

API_BASE   = "http://127.0.0.1:8000"
OUT_DIR    = Path("certs")
DELAY_SEC  = 1


def download_bundle(nid: str, job_id: str) -> tuple[bool, str]:
    try:
        r = httpx.get(f"{API_BASE}/jobs/{job_id}/certificates/bundle", timeout=30)
        if r.status_code == 200:
            out_path = OUT_DIR / f"{nid}.pdf"
            out_path.write_bytes(r.content)
            size_kb = len(r.content) // 1024
            return True, f"{out_path} ({size_kb} KB)"
        return False, f"HTTP {r.status_code} — {r.text[:100]}"
    except Exception as e:
        return False, str(e)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/bulk_download.py jobs.csv")
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
    print(f"📋 {len(rows)} jobs | บันทึกไปที่ {OUT_DIR.resolve()}\n")

    ok_list, fail_list = [], []
    for i, (nid, job_id) in enumerate(rows, 1):
        label = f"{nid[:4]}***{nid[-3:]}"
        print(f"[{i}/{len(rows)}] {label} ...", end=" ", flush=True)
        success, msg = download_bundle(nid, job_id)
        if success:
            print(f"✅ {msg}")
            ok_list.append(nid)
        else:
            print(f"⏳ {msg} (งานอาจยังไม่เสร็จ)")
            fail_list.append((nid, job_id, msg))
        if i < len(rows):
            time.sleep(DELAY_SEC)

    print(f"\n{'═'*55}")
    print(f"✅ ดาวน์โหลดสำเร็จ : {len(ok_list)}/{len(rows)}")
    print(f"⏳ ยังไม่พร้อม     : {len(fail_list)}/{len(rows)}")

    if fail_list:
        print("\nรายการที่ยังไม่ได้:")
        for nid, job_id, reason in fail_list:
            print(f"  {nid} (job: {job_id[:8]}...) → {reason}")
        print("\nลองรันใหม่อีกครั้งเมื่องานเสร็จครบครับ")


if __name__ == "__main__":
    main()
