from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Job, Payment

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(security)):
    if creds.username != "admin" or creds.password != settings.admin_password:
        raise HTTPException(
            status_code=401,
            detail="รหัสผ่านไม่ถูกต้อง",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/jobs", dependencies=[Depends(require_admin)])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(selectinload(Job.payment)).order_by(Job.created_at.desc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "status": j.status.value,
            "courses": j.courses,
            "total_price": j.total_price,
            "created_at": j.created_at.isoformat(),
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "payment_verified": j.payment.verified if j.payment else False,
        }
        for j in jobs
    ]


@router.post("/jobs/{job_id}/force-verify", dependencies=[Depends(require_admin)])
async def force_verify(job_id: str, db: AsyncSession = Depends(get_db)):
    """บังคับผ่านการตรวจสลิป — สำหรับ test เท่านั้น"""
    from datetime import datetime, timezone
    from app.models import JobStatus

    result = await db.execute(select(Payment).where(Payment.job_id == job_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="ไม่พบ payment")

    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบ job")

    # Guard: ห้าม force-verify ถ้า job กำลังทำงาน/จบ — กัน double-dispatch
    if job.status not in (JobStatus.pending, JobStatus.failed):
        raise HTTPException(
            status_code=409,
            detail=f"ไม่สามารถ force-verify ได้ — job อยู่สถานะ {job.status.value}",
        )

    payment.verified = True
    payment.verified_at = datetime.now(timezone.utc)
    # หมายเหตุ: payment.amount column = String(10) → ห้ามใส่ string ยาวกว่านี้
    payment.amount = "admin"

    job.status = JobStatus.queued
    await db.commit()

    from app.worker.tasks import run_automation
    run_automation.delay(str(job_id))

    return {"message": f"Job {job_id} ส่งเข้า queue แล้ว"}


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """ลบ job — สำหรับ test เท่านั้น"""
    from sqlalchemy import delete
    from app.models import JobLog, Certificate

    for model in [JobLog, Certificate, Payment, Job]:
        await db.execute(delete(model).where(model.job_id == job_id if model != Job else model.id == job_id))
    await db.commit()
    return {"message": "ลบแล้ว"}
