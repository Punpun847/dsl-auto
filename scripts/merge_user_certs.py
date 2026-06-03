"""Merge ทุก cert ของ user เดียวจากทุก jobs → ไฟล์เดียว

Usage:
    python scripts/merge_user_certs.py <NID>

จะอ่าน DB หา jobs ทั้งหมดของ NID นั้น → รวม cert ทุกใบ → save ที่ certs/<NID>.pdf
"""
import hashlib
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from sqlalchemy import create_engine, text


DB_URL    = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
API_BASE  = "http://127.0.0.1:8000"
OUT_DIR   = Path("certs")


def nid_hash(nid: str) -> str:
    return hashlib.sha256(nid.encode()).hexdigest()


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/merge_user_certs.py <NID>")
        sys.exit(1)

    nid = sys.argv[1].strip()
    h = nid_hash(nid)

    engine = create_engine(DB_URL)
    with engine.connect() as c:
        # หา jobs ทั้งหมดของ user นี้ (nid_hash) ที่ status=done
        rows = c.execute(
            text("""
                SELECT j.id, COUNT(cert.id) as n_certs
                FROM jobs j
                LEFT JOIN certificates cert ON cert.job_id = j.id
                WHERE j.nid_hash = :h AND j.status IN ('done', 'running')
                GROUP BY j.id
                ORDER BY j.created_at
            """),
            {"h": h},
        ).fetchall()

    if not rows:
        print(f"❌ ไม่พบ jobs สำหรับ NID {nid}")
        return

    print(f"📋 NID {nid[:4]}***{nid[-3:]} — {len(rows)} jobs")

    # ดึง cert paths จาก DB ตรงๆ (รวดเร็ว ไม่ผ่าน API)
    all_pdf_paths = []
    with engine.connect() as c:
        for job_id, n in rows:
            print(f"  job {str(job_id)[:8]}... → {n} certs")
            paths = c.execute(
                text("SELECT course_id, pdf_path FROM certificates WHERE job_id = :jid AND pdf_path IS NOT NULL"),
                {"jid": str(job_id)},
            ).fetchall()
            for course_id, pdf_path in paths:
                if pdf_path and Path(pdf_path).exists():
                    all_pdf_paths.append((course_id, pdf_path))

    print(f"\n📄 ทั้งหมด {len(all_pdf_paths)} ไฟล์ PDF — กำลัง merge…")

    # Merge
    writer = PdfWriter()
    merged = 0
    for course_id, pdf_path in all_pdf_paths:
        try:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)
            merged += 1
            print(f"  ✅ course {course_id}: {Path(pdf_path).name}")
        except Exception as e:
            print(f"  ❌ course {course_id}: error {e}")

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{nid}.pdf"
    with open(out_path, "wb") as f:
        writer.write(f)

    size_kb = out_path.stat().st_size // 1024
    print(f"\n💾 saved: {out_path} ({size_kb} KB, {merged} certificates)")


if __name__ == "__main__":
    main()
