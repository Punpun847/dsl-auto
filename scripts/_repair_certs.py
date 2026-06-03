"""Repair script — re-download certs ที่ pdf_path=NULL ใน DB

ใช้เมื่อ job done แล้วแต่บาง cert ไม่ได้ถูก download
(เกิดจาก Redis credential ถูกลบหลัง job done ทำให้ retry_pending_certs ทำงานไม่ได้)

Usage:
    python scripts/_repair_certs.py
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# แก้ไขตรงนี้: jobs ที่ต้องซ่อม
# format: (job_id, nid, pwd, [course_id, ...])
# ──────────────────────────────────────────
REPAIR_JOBS = [
    (
        "a17f0095-a700-43cb-a5e6-bea171e95fec",  # 1809***905 — retry courses 1003, 922
        "1809200030905",
        "waiyawat20092548",
        ["1003", "922"],
    ),
]

SET_BASE = "https://elearning.set.or.th/SETStudentLoan"


async def _get_enroll_id(page, course_id: str) -> int | None:
    """ดึง enroll_id จาก SET API สำหรับ course ที่ลงทะเบียนไว้แล้ว"""
    result = await page.evaluate(f"""async () => {{
        const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',
            {{ credentials: 'include' }});
        const d = await r.json();
        return d.enroll_id || null;
    }}""")
    return result


async def repair():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from sqlalchemy import update

    from app.config import settings
    from app.models import Certificate
    from app.worker.dsl_client import DSLClient

    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False)

    total_ok = 0

    for job_id, nid, pwd, course_ids in REPAIR_JOBS:
        logger.info(f"\n{'='*50}")
        logger.info(f"Job: {job_id[:8]}  NID: {nid[:4]}***{nid[-3:]}  courses: {course_ids}")
        cert_dir = ROOT / "uploads" / "certs" / job_id

        client = DSLClient()
        try:
            await client.start()

            # Login DSL
            logger.info("🔑 Login DSL...")
            ok = await client.login(nid=nid, pwd=pwd)
            if not ok:
                logger.error(f"❌ Login ไม่สำเร็จ: {client.last_error}")
                continue

            # SSO → SET
            logger.info("🔍 SSO → SET...")
            in_set = await client.goto_set()
            if not in_set:
                logger.error("❌ SSO ไม่สำเร็จ")
                continue

            logger.info("✅ เข้า SET แล้ว")

            for course_id in course_ids:
                logger.info(f"\n  📚 course={course_id} — รันเต็มคอร์ส (pre-test→video→post-test→exam→survey→cert)")

                async def _log(t, msg, prog=None):
                    logger.info(f"    [{t}] {msg}")

                # รัน full course automation — cert record มีอยู่แล้ว (pdf_path=NULL)
                pdf_path = await client.complete_course_via_api(
                    course_id=str(course_id),
                    on_log=_log,
                    cert_dir=cert_dir,
                )

                if not pdf_path:
                    logger.error(f"  ❌ ยังไม่ได้ cert — ดู log ด้านบน")
                    continue

                logger.info(f"  ✅ cert saved: {pdf_path}")

                # Update cert record ที่มีอยู่แล้ว (pdf_path=NULL → path จริง)
                async with SessionMaker() as db:
                    await db.execute(
                        update(Certificate)
                        .where(
                            Certificate.job_id == job_id,
                            Certificate.course_id == str(course_id),
                        )
                        .values(pdf_path=str(pdf_path))
                    )
                    await db.commit()
                    logger.info(f"  ✅ updated pdf_path ใน DB")
                    total_ok += 1

        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
        finally:
            await client.close()

    await engine.dispose()
    logger.info(f"\n{'='*50}")
    logger.info(f"เสร็จ — แก้สำเร็จ {total_ok}/{sum(len(c) for *_, c in REPAIR_JOBS)} certs")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Repair certs with NULL pdf_path")
    parser.add_argument("--job-id", dest="job_id", help="Job UUID")
    parser.add_argument("--nid", help="NID (13 digits)")
    parser.add_argument("--pwd", help="Password")
    parser.add_argument("--courses", help="Comma-separated course IDs")
    args, _ = parser.parse_known_args()

    if args.job_id and args.nid and args.pwd and args.courses:
        # CLI / dashboard mode — override REPAIR_JOBS จาก args แทนการแก้ไฟล์มือ
        REPAIR_JOBS = [(
            args.job_id,
            args.nid,
            args.pwd,
            [c.strip() for c in args.courses.split(",") if c.strip()],
        )]

    asyncio.run(repair())
