import asyncio
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.worker.celery_app import celery

logger_module = logging.getLogger(__name__)


def _new_loop_run(coro):
    """รันใน fresh event loop — กัน Playwright internal state ค้างข้าม task"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


@celery.task(bind=True, name="run_automation", max_retries=1)
def run_automation(self, job_id: str) -> None:
    _new_loop_run(_run(job_id))


@celery.task(name="retry_pending_certs")
def retry_pending_certs() -> dict:
    """หา jobs ที่ status=done แต่มี certificate ที่ pdf_path=null → retry download
    รันทุก 15 นาทีโดย Celery beat. Limit batch ละ 5 jobs กัน overload"""
    return _new_loop_run_result(_retry_pending_certs())


@celery.task(name="cleanup_old_uploads")
def cleanup_old_uploads() -> dict:
    """ลบไฟล์ slip + cert dir ของ jobs ที่ failed/done เกิน 30 วัน — ลด disk usage"""
    return _new_loop_run_result(_cleanup_old_uploads())


def _new_loop_run_result(coro):
    """เหมือน _new_loop_run แต่คืนค่า — ใช้สำหรับ beat tasks ที่ต้องการ result"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


async def _run(job_id: str) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import redis.asyncio as aioredis

    from app.config import settings
    from app.models import Certificate, Job, JobStatus, Payment
    from app.utils.job_logger import log_job
    from app.utils.security import decrypt_password
    from app.worker.dsl_client import DSLClient

    # สร้าง engine ใหม่ทุกครั้งใน worker — กัน connection ติด event loop เดิม
    worker_engine = create_async_engine(
        settings.database_url, echo=False, poolclass=NullPool
    )
    WorkerSession = async_sessionmaker(worker_engine, expire_on_commit=False)

    # สร้าง redis client ใหม่ใน event loop นี้ — กัน "attached to a different loop"
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with WorkerSession() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            await redis.aclose()
            return

        # Guard: ไม่ทำงานซ้ำถ้า job เคยจบหรือกำลังทำอยู่
        if job.status not in (JobStatus.pending, JobStatus.queued):
            logger_module.warning(
                f"job {job_id} status={job.status.value} — skip (already processed)"
            )
            await redis.aclose()
            return

        # Guard: ต้อง verify payment ก่อน — กันบอทวิ่งฟรี
        pay_result = await db.execute(select(Payment).where(Payment.job_id == job_id))
        payment = pay_result.scalar_one_or_none()
        if not payment or not payment.verified:
            await log_job(
                db, job_id, "err",
                "ยังไม่ได้ตรวจสอบสลิป — กรุณา verify payment ก่อน",
                redis=redis,
            )
            job.status = JobStatus.failed
            await db.commit()
            await redis.aclose()
            return

        job.status = JobStatus.running
        await db.commit()
        enc_nid = await redis.get(f"job:{job_id}:nid")
        enc_pwd = await redis.get(f"job:{job_id}:pwd")
        if not enc_nid or not enc_pwd:
            await log_job(
                db, job_id, "err",
                "ไม่พบ session — หมดเวลาหรือมีข้อผิดพลาด",
                redis=redis,
            )
            job.status = JobStatus.failed
            await db.commit()
            await redis.aclose()
            return

        nid = decrypt_password(enc_nid)
        pwd = decrypt_password(enc_pwd)

        async def on_log(type: str, message: str, progress=None):
            await log_job(db, job_id, type, message, progress, redis=redis)

        cert_dir = Path(settings.upload_dir) / "certs" / str(job_id)
        client = DSLClient()

        try:
            await client.start()
            await on_log("sys", "กำลังเข้าสู่ระบบ DSL …")
            ok = await client.login(nid=nid, pwd=pwd)
            if not ok:
                raise RuntimeError(client.last_error or "login ไม่สำเร็จ")

            await on_log("ok", "เข้าระบบสำเร็จ — กำลัง SSO ไป SET")
            in_set = await client.goto_set()
            if not in_set:
                raise RuntimeError("เข้า SET e-learning ไม่ได้ (SSO ผิดปกติ)")

            total = max(len(job.courses), 1)
            for i, course_id in enumerate(job.courses, start=1):
                await on_log("sys", f"[{i}/{total}] เริ่มหลักสูตร {course_id}")
                pdf_path = await client.complete_course_via_api(
                    course_id=str(course_id),
                    on_log=on_log,
                    cert_dir=cert_dir,
                    job_id=job_id,
                )

                cert = Certificate(
                    job_id=job.id,
                    course_id=str(course_id),
                    pdf_path=pdf_path,
                )
                db.add(cert)
                await db.commit()

            # set done status ก่อน — กัน redis cleanup fail ทำให้ status ติด running
            job.status = JobStatus.done
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            await on_log("done", "งานเสร็จสมบูรณ์ ✅", "100")
            try:
                await redis.delete(f"job:{job_id}:nid", f"job:{job_id}:pwd")
            except Exception as e:
                logger_module.warning(f"redis cleanup error: {e}")


        except Exception as e:
            await log_job(
                db, job_id, "err",
                f"เกิดข้อผิดพลาด: {str(e)[:200]}",
                redis=redis,
            )
            job.status = JobStatus.failed
            await db.commit()
        finally:
            await client.close()

    await worker_engine.dispose()
    try:
        await redis.aclose()
    except Exception:
        pass


# ─────────────────────────── Beat Tasks ────────────────────────


async def _retry_pending_certs() -> dict:
    """หา Certificate rows ที่ pdf_path=null + job done ภายใน 24 ชม. → ลอง download อีกครั้ง

    Limit: 5 certs / รอบ — กัน overload + กัน SET anti-cheat
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.models import Certificate, Job, JobStatus
    from app.worker.dsl_client import DSLClient
    from app.utils.security import decrypt_password
    import redis.asyncio as aioredis

    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    retried, ok = 0, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    async with SessionMaker() as db:
        result = await db.execute(
            select(Certificate, Job)
            .join(Job, Certificate.job_id == Job.id)
            .where(
                Certificate.pdf_path.is_(None),
                Job.status == JobStatus.done,
                Job.completed_at >= cutoff,
            )
            .limit(5)
        )
        rows = list(result.all())

        if not rows:
            await engine.dispose()
            await redis.aclose()
            return {"checked": 0, "retried": 0, "success": 0}

        for cert, job in rows:
            retried += 1
            enc_nid = await redis.get(f"job:{job.id}:nid")
            enc_pwd = await redis.get(f"job:{job.id}:pwd")
            if not enc_nid or not enc_pwd:
                logger_module.info(
                    f"retry_cert: job {job.id} session expired — skip"
                )
                continue
            nid = decrypt_password(enc_nid)
            pwd = decrypt_password(enc_pwd)

            cert_dir = Path(settings.upload_dir) / "certs" / str(job.id)
            client = DSLClient()
            try:
                await client.start()
                if not await client.login(nid, pwd):
                    continue
                if not await client.goto_set():
                    continue
                pdf_path = await client.complete_course_via_api(
                    course_id=cert.course_id,
                    cert_dir=cert_dir,
                )
                if pdf_path:
                    cert.pdf_path = pdf_path
                    await db.commit()
                    ok += 1
                    logger_module.info(f"retry_cert: ✅ job={job.id} course={cert.course_id}")
            except Exception as e:
                logger_module.warning(f"retry_cert error: {e}")
            finally:
                await client.close()

    await engine.dispose()
    await redis.aclose()
    return {"checked": len(rows), "retried": retried, "success": ok}


async def _cleanup_old_uploads() -> dict:
    """ลบไฟล์เก่าจาก uploads/slips/ + uploads/certs/ ที่ job เก่ากว่า 30 วัน"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.models import Job, JobStatus, Payment

    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    slip_count, cert_count = 0, 0

    async with SessionMaker() as db:
        # หา jobs ที่ done/failed เกิน 30 วัน
        result = await db.execute(
            select(Job, Payment)
            .join(Payment, Payment.job_id == Job.id, isouter=True)
            .where(
                Job.status.in_([JobStatus.done, JobStatus.failed]),
                Job.created_at < cutoff,
            )
        )
        for job, payment in result.all():
            if payment and payment.slip_path:
                try:
                    p = Path(payment.slip_path)
                    if p.exists():
                        p.unlink()
                        slip_count += 1
                except Exception as e:
                    logger_module.warning(f"cleanup slip {payment.slip_path}: {e}")

            cert_dir = Path(settings.upload_dir) / "certs" / str(job.id)
            if cert_dir.exists():
                try:
                    shutil.rmtree(cert_dir, ignore_errors=True)
                    cert_count += 1
                except Exception as e:
                    logger_module.warning(f"cleanup cert dir {cert_dir}: {e}")

    await engine.dispose()
    logger_module.info(
        f"cleanup: slips_deleted={slip_count} cert_dirs_deleted={cert_count}"
    )
    return {"slips_deleted": slip_count, "cert_dirs_deleted": cert_count}
