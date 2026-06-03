import asyncio
import io
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_optional_user
from app.config import settings
from app.database import get_db
from app.models import Certificate, Job, JobStatus, Payment
from app.models.user import User
from app.schemas.job import JobCreate, JobOut
from app.utils.redis_client import get_redis
from app.utils.security import encrypt_password, hash_nid

router = APIRouter()


def _check_ownership(job: Job, user: Optional[User]) -> None:
    """Raise 403 ถ้า job มี user_id แต่ user ปัจจุบันไม่ตรง

    Job ที่ user_id=None (anonymous) เข้าได้ทุกคนที่รู้ UUID (backward-compat)
    Job ที่มี user_id ต้อง match — admin bypass ได้
    """
    if job.user_id is None:
        return
    if user is None:
        raise HTTPException(status_code=401, detail="งานนี้ต้องล็อกอินก่อน")
    if user.is_admin:
        return
    if str(job.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงงานนี้")


def _sync_celery_ping() -> bool:
    try:
        from app.worker.celery_app import celery
        # timeout 5s — ถ้า workers ยุ่งกับ task (solo pool) อาจตอบ ping ช้า
        return bool(celery.control.inspect(timeout=5.0).ping())
    except Exception:
        return False


async def _celery_worker_alive() -> bool:
    """ตรวจว่ามี celery worker active หรือไม่ — รันใน thread pool กัน block event loop"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_celery_ping)


@router.post("/", response_model=JobOut, status_code=201)
async def create_job(
    nid: str = Form(...),
    pwd: str = Form(...),
    courses: str = Form(...),          # JSON string: '["anti","fin"]'
    total_price: str = Form("0"),
    total_hours: str = Form(...),
    slip: Optional[UploadFile] = File(None),  # optional ใน FREE_MODE
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    # ข้าม celery ping check — ping fail บ่อยถ้า workers ทุกตัวยุ่ง (solo pool)
    # ถ้า celery ตายจริง job จะค้าง pending ใน DB → admin ดู status ได้

    # FREE_MODE — ไม่บังคับสลิป + total_price = 0
    if settings.free_mode:
        total_price = "0"
    elif slip is None:
        raise HTTPException(
            status_code=422,
            detail="ต้องแนบสลิปการโอนเงิน (FREE_MODE ปิดอยู่)",
        )

    # Validate ด้วย schema
    payload = JobCreate(
        nid=nid, pwd=pwd,
        courses=json.loads(courses),
        total_price=total_price,
        total_hours=total_hours,
    )

    # บันทึกสลิป (ถ้ามี)
    slip_path = None
    if slip is not None:
        upload_dir = Path(settings.upload_dir) / "slips"
        upload_dir.mkdir(parents=True, exist_ok=True)
        slip_filename = f"{uuid.uuid4()}{Path(slip.filename).suffix}"
        slip_path = upload_dir / slip_filename
        slip_path.write_bytes(await slip.read())

    # Server-side price verification — ข้ามใน FREE_MODE
    if not settings.free_mode:
        try:
            client_price = float(payload.total_price)
        except (TypeError, ValueError):
            client_price = 0

        expected_price = 0.0
        cache_used = False
        try:
            import hashlib as _h
            import json as _j
            redis_pre = get_redis()
            cached = await redis_pre.get(f"courses:nid:{_h.sha256(payload.nid.encode()).hexdigest()}")
            if cached:
                hours_map = _j.loads(cached)
                from app.worker.dsl_client import PRICE_PER_HOUR
                for cid in payload.courses:
                    hrs = hours_map.get(str(cid))
                    if hrs is not None:
                        expected_price += max(1, round(hrs * PRICE_PER_HOUR))
                cache_used = expected_price > 0
        except Exception:
            pass

        if not cache_used:
            expected_price = max(1, len(payload.courses)) * 3

        # tolerance ±5% เผื่อ rounding
        if client_price + 0.5 < expected_price * 0.95:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"total_price ไม่ตรง: ส่งมา {client_price:.0f} บาท "
                    f"แต่ระบบคำนวณ {expected_price:.0f} บาท "
                    f"({'จาก /courses/fetch cache' if cache_used else 'minimum floor'})"
                ),
            )

    # สร้าง Job — ผูก user_id ถ้า login แล้ว
    job = Job(
        user_id=user.id if user else None,
        nid_hash=hash_nid(payload.nid),
        courses=payload.courses,
        total_price=payload.total_price,
        total_hours=payload.total_hours,
        status=JobStatus.pending,
    )
    db.add(job)
    await db.flush()

    # สร้าง Payment record
    # FREE_MODE: payment auto-verified, slip_path = "FREE"
    from datetime import datetime, timezone
    payment = Payment(
        job_id=job.id,
        slip_path=str(slip_path) if slip_path else "FREE",
        verified=settings.free_mode,
        verified_at=datetime.now(timezone.utc) if settings.free_mode else None,
        amount="0" if settings.free_mode else None,
    )
    db.add(payment)
    if settings.free_mode:
        job.status = JobStatus.queued
    await db.commit()
    await db.refresh(job)

    # บันทึก NID → registry (best-effort) ให้ dashboard reverse hash กลับเป็น NID ได้
    # job สำคัญกว่า display — ถ้า registry เขียนพลาดก็ปล่อยผ่าน
    try:
        from app.utils.nid_registry import record_nid
        record_nid(payload.nid)
    except Exception:
        pass

    # เก็บ NID + รหัสผ่านที่เข้ารหัสไว้ใน Redis (TTL 2 ชั่วโมง)
    redis = get_redis()
    await redis.setex(f"job:{job.id}:nid", 7200, encrypt_password(payload.nid))
    await redis.setex(f"job:{job.id}:pwd", 7200, encrypt_password(payload.pwd))

    # FREE_MODE: dispatch worker เลย — ไม่ต้องรอ verify_payment
    if settings.free_mode:
        from app.worker.tasks import run_automation
        run_automation.delay(str(job.id))

    await db.refresh(job, ["logs"])
    return job


async def _load_job_with_check(
    job_id: str, db: AsyncSession, user: Optional[User], *, with_logs: bool = False
) -> Job:
    stmt = select(Job).where(Job.id == job_id)
    if with_logs:
        stmt = stmt.options(selectinload(Job.logs))
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    _check_ownership(job, user)
    return job


@router.get("/", response_model=list[JobOut])
async def list_my_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """List jobs ของ user ปัจจุบัน — ต้อง login"""
    if not user:
        raise HTTPException(status_code=401, detail="ต้องล็อกอินก่อน")
    result = await db.execute(
        select(Job)
        .where(Job.user_id == user.id)
        .options(selectinload(Job.logs))
        .order_by(Job.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    return await _load_job_with_check(job_id, db, user, with_logs=True)


@router.get("/{job_id}/certificates")
async def list_certificates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """คืน list ของ cert ทุกหลักสูตรใน job นี้"""
    await _load_job_with_check(job_id, db, user)
    result = await db.execute(
        select(Certificate).where(Certificate.job_id == job_id)
    )
    certs = result.scalars().all()
    return [
        {
            "course_id": c.course_id,
            "ready": bool(c.pdf_path and os.path.exists(c.pdf_path)),
            "download_url": f"/jobs/{job_id}/certificate?course_id={c.course_id}",
        }
        for c in certs
    ]


@router.get("/{job_id}/certificates/bundle")
async def download_bundle(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """รวมวุฒิบัตรทุกหลักสูตรของ job นี้ใส่ PDF เดียว แล้วส่งให้โหลด"""
    await _load_job_with_check(job_id, db, user)
    result = await db.execute(
        select(Certificate).where(Certificate.job_id == job_id).order_by(Certificate.issued_at)
    )
    certs = result.scalars().all()
    if not certs:
        raise HTTPException(status_code=404, detail="ยังไม่มีวุฒิบัตร")

    writer = PdfWriter()
    merged = 0
    missing = 0
    for c in certs:
        if not c.pdf_path or not os.path.exists(c.pdf_path):
            missing += 1
            continue
        try:
            reader = PdfReader(c.pdf_path)
            for page in reader.pages:
                writer.add_page(page)
            merged += 1
        except Exception:
            missing += 1
            continue

    if merged == 0:
        raise HTTPException(status_code=404, detail="ไฟล์ PDF ทั้งหมดหายไปหรือเสียหาย")

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="certificates_{job_id[:8]}.pdf"',
            "X-Merged-Count": str(merged),
            "X-Missing-Count": str(missing),
        },
    )


@router.get("/{job_id}/certificate")
async def get_certificate(
    job_id: str,
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    await _load_job_with_check(job_id, db, user)
    result = await db.execute(
        select(Certificate).where(
            Certificate.job_id == job_id,
            Certificate.course_id == course_id,
        )
    )
    cert = result.scalar_one_or_none()
    if not cert or not cert.pdf_path:
        raise HTTPException(status_code=404, detail="ยังไม่มีวุฒิบัตร")
    if not os.path.exists(cert.pdf_path):
        raise HTTPException(status_code=404, detail="ไฟล์ PDF หายไป")
    return FileResponse(cert.pdf_path, media_type="application/pdf", filename=f"cert_{course_id}.pdf")
