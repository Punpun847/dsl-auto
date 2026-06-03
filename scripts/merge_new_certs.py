"""Merge เฉพาะ cert ที่ออกใหม่วันนี้ (filter ใบเก่าออก)

Usage:
    python scripts/merge_new_certs.py <NID> [--days 1]
"""
import argparse
import hashlib
import re
import sys
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent
DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
OUT_DIR = ROOT / "certs"


def parse_cert_dates_from_logs() -> dict:
    """Scan celery*.log files → return {(job_id, course_id): cert_date}"""
    cert_map = {}
    last_date = None  # คงค่า cert_datetime ล่าสุดที่อ่านได้

    log_files = list(ROOT.glob("celery*.log")) + list(ROOT.glob("uvicorn.log"))
    for log_path in log_files:
        last_date = None
        try:
            with open(log_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # Pattern 1: cert try → certificate_datetime
                    m = re.search(r"certificate_datetime=(\d{4}-\d{2}-\d{2})", line)
                    if m:
                        last_date = m.group(1)
                        continue
                    # Pattern 2: cert saved (อยู่หลัง datetime)
                    m = re.search(r"uploads[\\/]certs[\\/]([^\\/]+)[\\/]cert_(\d+)\.pdf", line)
                    if m and last_date:
                        job_id = m.group(1)
                        course_id = m.group(2)
                        cert_map[(job_id, course_id)] = last_date
                        last_date = None  # ใช้แล้วเคลียร์
        except Exception:
            continue
    return cert_map


def merge_for_user(nid: str, since_date: str):
    """Merge cert ที่ออก >= since_date เท่านั้น"""
    h = hashlib.sha256(nid.encode()).hexdigest()
    engine = create_engine(DB)

    print(f"📋 NID {nid[:4]}***{nid[-3:]} — กรอง cert ตั้งแต่ {since_date}")

    # หา certs ของ user นี้
    with engine.connect() as c:
        certs = c.execute(
            text("""
                SELECT cert.job_id, cert.course_id, cert.pdf_path
                FROM certificates cert
                JOIN jobs j ON cert.job_id = j.id
                WHERE j.nid_hash = :h AND cert.pdf_path IS NOT NULL
                ORDER BY cert.issued_at
            """),
            {"h": h},
        ).fetchall()

    if not certs:
        print(f"  ❌ ไม่พบ cert PDF")
        return

    # Parse cert dates จาก celery logs
    cert_dates = parse_cert_dates_from_logs()

    # Filter
    new_certs = []
    old_certs = []
    unknown_certs = []
    for job_id, course_id, pdf_path in certs:
        date = cert_dates.get((str(job_id), str(course_id)))
        if date is None:
            unknown_certs.append((course_id, pdf_path))
        elif date >= since_date:
            new_certs.append((course_id, pdf_path, date))
        else:
            old_certs.append((course_id, pdf_path, date))

    print(f"  ✅ ใหม่ (>= {since_date}): {len(new_certs)} ใบ")
    print(f"  ⏭️  เก่า (filter ออก): {len(old_certs)} ใบ")
    if unknown_certs:
        print(f"  ❓ ไม่รู้ date: {len(unknown_certs)} ใบ — assume ใหม่")
        for c, p in unknown_certs:
            new_certs.append((c, p, "?"))

    # Merge
    writer = PdfWriter()
    merged = 0
    for course_id, pdf_path, date in new_certs:
        try:
            if not Path(pdf_path).exists():
                print(f"  ⚠️  ไฟล์หาย: {pdf_path}")
                continue
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)
            merged += 1
            print(f"     course {course_id} [{date}]")
        except Exception as e:
            print(f"  ❌ {course_id}: {e}")

    if merged == 0:
        print(f"  ⚠️  ไม่มี cert ใหม่ — ไม่สร้างไฟล์")
        return

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{nid}.pdf"
    with open(out_path, "wb") as f:
        writer.write(f)
    size_kb = out_path.stat().st_size // 1024
    print(f"  💾 {out_path} ({size_kb} KB, {merged} certs)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("nid", nargs="?")
    p.add_argument("--all", action="store_true", help="ทำทุกคนใน accounts.csv")
    p.add_argument("--days", type=int, default=1, help="ใช้ cert ที่ออกใน N วันล่าสุด (default 1)")
    args = p.parse_args()

    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    if args.all:
        accounts_file = ROOT / "accounts.csv"
        with open(accounts_file, encoding="utf-8-sig") as f:
            nids = [line.split(",")[0].strip() for line in f if line.strip()]
        for nid in nids:
            print(f"\n{'='*60}")
            merge_for_user(nid, since)
    elif args.nid:
        merge_for_user(args.nid, since)
    else:
        print("Usage: python scripts/merge_new_certs.py <NID|--all> [--days N]")


if __name__ == "__main__":
    main()
