"""Admin panel API — JWT-gated (is_admin) endpoints สำหรับหน้า admin dashboard ใหม่
แยกจาก admin.py เดิม (HTTP Basic) — อันนี้ใช้ระบบ JWT เดียวกับ customer (User.is_admin)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.api.auth import get_current_user
from app.models import Job, JobStatus, Payment, Certificate, User
from app.utils.redis_client import get_redis
from app.utils.runtime_settings import get_free_mode, set_free_mode

router = APIRouter(prefix="/admin", tags=["admin-panel"])

BANK_KEY = "dsl:answer_cache"


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """ต้องเป็น user ที่ is_admin=true เท่านั้น (ไม่ใช่ → 403)"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลระบบเท่านั้น")
    return user


def _price_int(v) -> int:
    try:
        return int(float(str(v or 0)))
    except (ValueError, TypeError):
        return 0


# ───────────────────────── Dashboard / System ─────────────────────────
@router.get("/overview")
async def overview(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    # job counts by status
    rows = (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    by_status = {s.value: 0 for s in JobStatus}
    for st, cnt in rows:
        by_status[st.value] = cnt
    total_jobs = sum(by_status.values())

    # today
    start_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_jobs = (await db.execute(
        select(func.count()).select_from(Job).where(Job.created_at >= start_today)
    )).scalar() or 0

    # revenue (เฉพาะ payment ที่ verified)
    paid_jobs = (await db.execute(
        select(Job.total_price).join(Payment, Payment.job_id == Job.id).where(Payment.verified == True)  # noqa: E712
    )).scalars().all()
    revenue = sum(_price_int(p) for p in paid_jobs)

    certs = (await db.execute(select(func.count()).select_from(Certificate))).scalar() or 0
    users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    # success rate
    done = by_status.get("done", 0)
    failed = by_status.get("failed", 0)
    finished = done + failed
    success_rate = round(done / finished * 100) if finished else 0

    # ── system: redis bank + queue, celery workers ──
    bank_size = 0
    queue_len = 0
    try:
        r = get_redis()
        bank_size = await r.hlen(BANK_KEY)
        queue_len = await r.llen("celery")
    except Exception:
        pass

    workers = 0
    try:
        from app.worker.celery_app import celery
        ping = celery.control.inspect(timeout=2).ping() or {}
        workers = len(ping)
    except Exception:
        pass

    return {
        "jobs": {"total": total_jobs, "today": today_jobs, "by_status": by_status,
                 "success_rate": success_rate},
        "revenue": revenue,
        "certs": certs,
        "users": users,
        "system": {
            "workers": workers,
            "bank_size": bank_size,
            "queue_len": queue_len,
            "free_mode": await get_free_mode(),
            "price_per_hour": getattr(settings, "price_per_hour", 3),
        },
    }


# ───────────────────────── Jobs ─────────────────────────
@router.get("/panel/jobs")
async def panel_jobs(
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job).options(selectinload(Job.payment), selectinload(Job.user)).order_by(Job.created_at.desc())
    if status and status != "all":
        try:
            stmt = stmt.where(Job.status == JobStatus(status))
        except ValueError:
            pass
    jobs = (await db.execute(stmt.limit(limit))).scalars().all()
    out = []
    for j in jobs:
        if q and q.lower() not in (j.nid_hash or "").lower() and q.lower() not in (
            (j.user.email if j.user else "") or "").lower() and q.lower() not in str(j.id).lower():
            continue
        out.append({
            "id": str(j.id),
            "email": j.user.email if j.user else None,
            "status": j.status.value,
            "courses": j.courses,
            "n_courses": len(j.courses or []),
            "total_price": j.total_price,
            "total_hours": j.total_hours,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "payment_verified": j.payment.verified if j.payment else False,
        })
    return out


@router.post("/panel/jobs/{job_id}/retry")
async def retry_job(job_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "ไม่พบ job")
    if job.status == JobStatus.running:
        raise HTTPException(409, "job กำลังทำงานอยู่")
    job.status = JobStatus.queued
    await db.commit()
    from app.worker.tasks import run_automation
    run_automation.delay(str(job_id))
    return {"message": "ส่งเข้า queue ใหม่แล้ว"}


@router.delete("/panel/jobs/{job_id}")
async def panel_delete_job(job_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    from app.models import JobLog
    for model in [JobLog, Certificate, Payment, Job]:
        await db.execute(delete(model).where(model.job_id == job_id if model is not Job else model.id == job_id))
    await db.commit()
    return {"message": "ลบแล้ว"}


# ───────────────────────── Users ─────────────────────────
@router.get("/panel/users")
async def panel_users(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    # job count per user
    counts = dict((await db.execute(
        select(Job.user_id, func.count()).group_by(Job.user_id)
    )).all())
    return [{
        "id": str(u.id),
        "email": u.email,
        "is_admin": u.is_admin,
        "is_active": u.is_active,
        "jobs": counts.get(u.id, 0),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]


@router.post("/panel/users/{user_id}/toggle-admin")
async def toggle_admin(user_id: str, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(404, "ไม่พบ user")
    u.is_admin = not u.is_admin
    await db.commit()
    return {"id": str(u.id), "is_admin": u.is_admin}


# ───────────────────────── Payments ─────────────────────────
@router.get("/panel/payments")
async def panel_payments(admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    pays = (await db.execute(
        select(Payment).order_by(Payment.created_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": str(p.id),
        "job_id": str(p.job_id),
        "amount": p.amount,
        "reference": p.reference,
        "recipient": p.recipient,
        "verified": p.verified,
        "slip_path": p.slip_path,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in pays]


# ───────────────────────── Answer Bank ─────────────────────────
@router.get("/panel/bank")
async def panel_bank(admin: User = Depends(get_current_admin)):
    size = 0
    sample = []
    try:
        r = get_redis()
        size = await r.hlen(BANK_KEY)
        cur = 0
        cur, items = await r.hscan(BANK_KEY, cursor=0, count=8)
        sample = [{"hash": k, "value": v[:60]} for k, v in list(items.items())[:8]]
    except Exception as e:
        return {"size": 0, "sample": [], "error": str(e)}
    return {"size": size, "sample": sample}


# ───────────────────────── Admin: รันงานฟรีเอง ─────────────────────────
@router.post("/panel/run-free")
async def admin_run_free(
    payload: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """สร้างงานให้แอดมินรัน "ฟรีเสมอ" — ไม่สนค่า FREE_MODE global, ไม่ต้องแนบสลิป

    body: {nid, pwd, courses: [ids], total_hours}
    งานผูกกับบัญชี admin, payment auto-verified ("FREE"), dispatch worker ทันที
    """
    from app.utils.security import encrypt_password, hash_nid

    nid = str(payload.get("nid") or "").strip()
    pwd = str(payload.get("pwd") or "")
    courses = payload.get("courses") or []
    total_hours = str(payload.get("total_hours") or "0")

    # validate NID (13 หลัก + checksum) — ใช้ตัวเลขล้วน
    digits = "".join(c for c in nid if c.isdigit())
    if len(digits) != 13:
        raise HTTPException(422, "เลขบัตรประชาชนต้อง 13 หลัก")
    if not pwd:
        raise HTTPException(422, "ต้องกรอกรหัสผ่าน")
    if not isinstance(courses, list) or not courses:
        raise HTTPException(422, "ต้องเลือกอย่างน้อย 1 คอร์ส")
    courses = [str(c) for c in courses]

    # สร้าง Job — ฟรีเสมอ ผูกกับ admin
    job = Job(
        user_id=admin.id,
        nid_hash=hash_nid(digits),
        courses=courses,
        total_price="0",
        total_hours=total_hours,
        status=JobStatus.queued,
    )
    db.add(job)
    await db.flush()

    payment = Payment(
        job_id=job.id,
        slip_path="FREE",
        verified=True,
        verified_at=datetime.now(timezone.utc),
        amount="0",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(job)

    # registry (best-effort) ให้ dashboard reverse hash ได้
    try:
        from app.utils.nid_registry import record_nid
        record_nid(digits)
    except Exception:
        pass

    # เก็บ credential เข้ารหัสใน Redis (TTL 2 ชม.) ให้ worker ใช้
    r = get_redis()
    await r.setex(f"job:{job.id}:nid", 7200, encrypt_password(digits))
    await r.setex(f"job:{job.id}:pwd", 7200, encrypt_password(pwd))

    # dispatch worker ทันที
    from app.worker.tasks import run_automation
    run_automation.delay(str(job.id))

    return {"id": str(job.id), "status": job.status.value, "n_courses": len(courses)}


# ───────────────────────── Workers: เปิด/ปิด/รีสตาร์ท ─────────────────────────
import asyncio as _asyncio
from pathlib import Path as _Path

_SCRIPTS_DIR = _Path(__file__).resolve().parents[2] / "scripts"


def _count_workers() -> int:
    """นับ celery worker ที่ออนไลน์ (ping)"""
    try:
        from app.worker.celery_app import celery
        return len(celery.control.inspect(timeout=2).ping() or {})
    except Exception:
        return 0


async def _run_worker_script(name: str, *args: str) -> dict:
    """รัน scripts/<name> แบบ async — คืน output + exit code"""
    script = _SCRIPTS_DIR / name
    if not script.exists():
        raise HTTPException(500, f"ไม่พบสคริปต์ {name}")
    proc = await _asyncio.create_subprocess_exec(
        "bash", str(script), *args,
        stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await _asyncio.wait_for(proc.communicate(), timeout=60)
    except _asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, "สคริปต์รันนานเกินไป (timeout)")
    return {"code": proc.returncode, "output": (out or b"").decode(errors="replace").strip()}


@router.get("/panel/workers")
async def workers_status(admin: User = Depends(get_current_admin)):
    """จำนวน celery worker ที่ออนไลน์"""
    n = await _asyncio.get_event_loop().run_in_executor(None, _count_workers)
    return {"count": n, "running": n > 0}


@router.post("/panel/workers/start")
async def workers_start(admin: User = Depends(get_current_admin)):
    res = await _run_worker_script("start_workers.sh", "4")
    n = await _asyncio.get_event_loop().run_in_executor(None, _count_workers)
    return {"message": res["output"], "count": n}


@router.post("/panel/workers/stop")
async def workers_stop(admin: User = Depends(get_current_admin)):
    res = await _run_worker_script("stop_workers.sh")
    return {"message": res["output"], "count": 0}


@router.post("/panel/workers/restart")
async def workers_restart(admin: User = Depends(get_current_admin)):
    res = await _run_worker_script("restart_workers.sh", "4")
    n = await _asyncio.get_event_loop().run_in_executor(None, _count_workers)
    return {"message": res["output"], "count": n}


# ───────────────────────── Settings: FREE_MODE toggle ─────────────────────────
@router.get("/panel/free-mode")
async def get_free_mode_status(admin: User = Depends(get_current_admin)):
    return {"free_mode": await get_free_mode()}


@router.post("/panel/free-mode")
async def toggle_free_mode(payload: dict, admin: User = Depends(get_current_admin)):
    """เปิด/ปิด FREE_MODE สำหรับลูกค้า (มีผลทันที ไม่ต้อง restart)"""
    on = bool(payload.get("on"))
    await set_free_mode(on)
    return {"free_mode": on}

