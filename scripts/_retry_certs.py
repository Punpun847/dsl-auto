"""Retry ดาวน์โหลด cert PDF สำหรับ courses ที่ pdf_path=None

Usage:
    python scripts/_retry_certs.py <NID> <PWD> <JOB_ID> [course_id1 course_id2 ...]

    ถ้าไม่ระบุ course_ids จะ retry ทุก cert ที่ pdf_path=None ของ job นั้น
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
from app.worker.dsl_client import DSLClient

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"


async def main():
    if len(sys.argv) < 4:
        print("Usage: python scripts/_retry_certs.py <NID> <PWD> <JOB_ID> [course_id1 ...]")
        sys.exit(1)

    nid     = sys.argv[1]
    pwd     = sys.argv[2]
    job_id  = sys.argv[3]
    wanted  = set(sys.argv[4:]) if len(sys.argv) > 4 else None

    engine = create_engine(DB)

    # หา certs ที่ pdf_path=None
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT course_id FROM certificates WHERE job_id=:j AND pdf_path IS NULL"
        ), {"j": job_id}).fetchall()

    missing = [str(r[0]) for r in rows]
    if wanted:
        missing = [c for c in missing if c in wanted]

    if not missing:
        print("✅ ไม่มี cert ที่ต้อง retry")
        return

    print(f"🔄 จะ retry {len(missing)} cert: {missing}")

    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        if not ok:
            print("❌ Login ไม่ได้")
            return
        print(f"✅ Login สำเร็จ")

        for course_id in missing:
            print(f"\n📥 Download cert สำหรับ course {course_id}...")
            try:
                pdf_bytes = await client.download_cert(course_id)
                if not pdf_bytes:
                    print(f"  ❌ ไม่ได้ PDF")
                    continue

                # บันทึก PDF
                out_dir = ROOT / "uploads" / "certs" / job_id
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"cert_{course_id}.pdf"
                out_path.write_bytes(pdf_bytes)
                print(f"  ✅ บันทึก: {out_path} ({len(pdf_bytes):,} bytes)")

                # อัพเดต DB
                with engine.connect() as c:
                    c.execute(text(
                        "UPDATE certificates SET pdf_path=:p WHERE job_id=:j AND course_id=:c"
                    ), {"p": str(out_path.relative_to(ROOT)), "j": job_id, "c": int(course_id)})
                    c.commit()
                print(f"  ✅ อัพเดต DB แล้ว")

            except Exception as e:
                print(f"  ❌ Error: {e}")

    print("\n✅ เสร็จแล้ว — รัน merge_new_certs.py อีกครั้งได้เลย")


if __name__ == "__main__":
    asyncio.run(main())
