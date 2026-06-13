import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from promptpay import qrcode as promptpay_qr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Job, JobStatus, Payment
from app.schemas.payment import PaymentOut
from app.utils.ocr import extract_slip
from app.utils.redis_client import get_redis
from app.utils.slipok import verify_slip as slipok_verify

router = APIRouter()


def _account_match(slip_recipient: str, expected: str, raw_text: str = "") -> bool:
    """เทียบเลขบัญชีโดยใช้ 4 ตัวสุดท้าย
    Fallback: ถ้า OCR แยก digit เป็น fragments — ค้น tail-4 ใน raw_text
    ตรงๆ (เช่น OCR อ่าน 'x-4759' เพี้ยนเป็น 'x4' + '759' แยกกัน)"""
    def tail(s): return "".join(c for c in s if c.isdigit())[-4:]
    expected_tail = tail(expected)
    if slip_recipient and tail(slip_recipient) == expected_tail:
        return True
    # fallback: หา expected_tail ใน digit-only ของ raw_text
    if raw_text and expected_tail:
        digits_only = "".join(c for c in raw_text if c.isdigit())
        if expected_tail in digits_only:
            return True
    return False


@router.get("/info")
async def payment_info():
    """คืนข้อมูลบัญชีรับเงิน สำหรับ frontend แสดงผล"""
    raw = settings.expected_account
    digits = "".join(c for c in raw if c.isdigit())
    # format เลขบัญชีธนาคาร 10 หลัก → XXX-X-XXXXX-X (กรุงไทย)
    if len(digits) == 10:
        display = f"{digits[:3]}-{digits[3:4]}-{digits[4:9]}-{digits[9:]}"
    else:
        display = raw
    from app.utils.runtime_settings import get_free_mode
    return {
        "account": display,
        "recipient_name": settings.expected_recipient_name or "เก็บชั่วโมงจิตอาสา กยศ ออนไลน์",
        "method": "โอนเข้าบัญชี",
        "free_mode": await get_free_mode(),
    }


def _promptpay_account() -> str:
    """ดึงเลข PromptPay (digits-only) จาก settings และ validate format"""
    account = "".join(c for c in settings.expected_account if c.isdigit())
    if len(account) not in (10, 13, 15):
        raise HTTPException(
            status_code=500,
            detail=(
                f"EXPECTED_ACCOUNT ไม่ถูกต้อง: ต้องเป็นเบอร์โทร 10 หลัก / "
                f"เลขบัตร 13 หลัก / eWallet 15 หลัก (ปัจจุบันได้ {len(account)} หลัก)"
            ),
        )
    return account


@router.get("/qr")
async def qr_for_amount(amount: float):
    """สร้าง PromptPay QR แบบล็อคจำนวนเงิน (ไม่ต้องมี job_id)"""
    if amount <= 0 or amount > 1_000_000:
        raise HTTPException(status_code=400, detail="amount ไม่ถูกต้อง")

    account = _promptpay_account()
    payload = promptpay_qr.generate_payload(account, amount)
    img = promptpay_qr.to_image(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@router.get("/{job_id}/qr")
async def get_payment_qr(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    สร้าง PromptPay QR แบบล็อคจำนวนเงิน (EMVCo format)
    คืนเป็น PNG image
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบ job")

    # เตรียม account — ตัด '-' และ space ออก (+ validate format)
    account = _promptpay_account()
    amount = float(job.total_price)

    # สร้าง EMVCo payload + render เป็น PIL image
    payload = promptpay_qr.generate_payload(account, amount)
    img = promptpay_qr.to_image(payload)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@router.post("/{job_id}/verify", response_model=PaymentOut)
async def verify_payment(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    OCR สลิป → ตรวจ 3 อย่าง:
      1. ยอดเงินตรงกับ job.total_price
      2. เลขบัญชีปลายทางตรงกับบริษัท
      3. ไม่ใช่สลิปที่เคยใช้แล้ว (ดูจาก reference)
    """
    payment_result = await db.execute(
        select(Payment).where(Payment.job_id == job_id)
    )
    payment = payment_result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลการชำระเงิน")

    if payment.verified:
        raise HTTPException(status_code=400, detail="สลิปนี้ตรวจสอบไปแล้ว")

    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบ job")

    # Guard: ห้าม verify ถ้า job กำลังทำงาน / จบไปแล้ว — กัน double-dispatch
    if job.status not in (JobStatus.pending, JobStatus.failed):
        raise HTTPException(
            status_code=409,
            detail=f"ไม่สามารถ verify ได้ — job อยู่สถานะ {job.status.value}",
        )

    # 1. ลอง SlipOK API ก่อน (verify ผ่าน ธปท. — แม่นกว่า OCR ของเรา)
    sok = await slipok_verify(payment.slip_path)
    using_slipok = False
    if sok and sok.get("success"):
        slip = {
            "amount": sok["amount"],
            "reference": sok["reference"],
            "recipient": sok["recipient"],
            "datetime": sok["datetime"],
            "bank": sok.get("bank_code") or "",
            "recipient_name": sok.get("recipient_name") or "",
            "raw_text": "",
        }
        using_slipok = True
    elif sok and not sok.get("success"):
        # SlipOK บอกว่าสลิปไม่ valid → ปฏิเสธทันที (ไม่ต้องลอง OCR ต่อ)
        raise HTTPException(
            status_code=422,
            detail={
                "message": "ตรวจสลิปไม่ผ่าน",
                "errors": [f"SlipOK: {sok.get('message') or 'สลิปไม่ถูกต้อง'}"],
            },
        )
    else:
        # SlipOK ไม่ได้ตั้งค่า หรือ error → fallback OCR
        slip = extract_slip(payment.slip_path)

    ocr_amount = slip["amount"]
    ocr_reference = slip["reference"]
    ocr_recipient = slip["recipient"]

    # ── ตรวจสอบก่อน set — เพื่อป้องกัน autoflush ชน unique constraint ──
    errors = []

    # 1. ยอดเงิน
    expected_amount = float(job.total_price)
    if ocr_amount is None:
        errors.append("อ่านยอดเงินจากสลิปไม่ได้ — รูปอาจเบลอเกินไป")
    elif abs(ocr_amount - expected_amount) > 0.5:
        errors.append(f"ยอดเงินไม่ตรง (สลิป: ฿{ocr_amount:.0f} ต้องจ่าย: ฿{expected_amount:.0f})")

    # 2. เลขบัญชี — ข้ามถ้า SlipOK verify ผ่าน (สลิปยืนยันแล้วว่าโอนเข้า branch ของเรา)
    if not using_slipok:
        if not _account_match(ocr_recipient or "", settings.expected_account, slip.get("raw_text") or ""):
            errors.append(f"เลขบัญชีปลายทางไม่ตรง (ต้องโอนเข้า {settings.expected_account})")

    # 3. สลิปซ้ำ — query ก่อน set payment.reference เพื่อหลีกเลี่ยง autoflush
    # ถ้าอ่าน reference ไม่ได้ทั้ง OCR/SlipOK → ปฏิเสธ (กัน replay attack)
    if not ocr_reference:
        errors.append("ไม่สามารถอ่านเลขอ้างอิงสลิปได้ — กรุณาส่งภาพที่ชัดเจน")
    else:
        with db.no_autoflush:
            dup_result = await db.execute(
                select(Payment).where(
                    Payment.reference == ocr_reference,
                    Payment.id != payment.id,
                )
            )
        if dup_result.scalar_one_or_none():
            errors.append("สลิปนี้เคยใช้กับ job อื่นแล้ว")

    # 4. เวลาที่สลิปสร้าง — ต้องไม่เก่าเกิน slip_max_age_minutes
    slip_dt = slip.get("datetime")
    if settings.slip_max_age_minutes > 0:
        if not slip_dt:
            errors.append("อ่านเวลาบนสลิปไม่ได้ — รูปอาจเบลอเกินไป")
        else:
            # สลิปเป็น Asia/Bangkok (UTC+7) — เทียบกับเวลาปัจจุบันโดยถือเป็น naive (local Thai time)
            now_th = datetime.now(timezone.utc) + timedelta(hours=7)
            now_th_naive = now_th.replace(tzinfo=None)
            age = now_th_naive - slip_dt
            if age > timedelta(minutes=settings.slip_max_age_minutes):
                mins = int(age.total_seconds() / 60)
                errors.append(f"สลิปเก่าเกินไป ({mins} นาที — รับไม่เกิน {settings.slip_max_age_minutes} นาที)")
            elif age < timedelta(minutes=-5):
                errors.append(f"เวลาบนสลิปอนาคต — สลิปอาจถูกแก้ไข")

    # 5. ธนาคาร — ข้ามถ้า SlipOK verify ผ่าน
    raw_text = (slip.get("raw_text") or "").lower()
    if not using_slipok:
        bank_keywords = [k.strip().lower() for k in settings.expected_bank_keywords.split(",") if k.strip()]
        if bank_keywords and slip.get("bank"):
            bank_found = slip["bank"].lower()
            if not any(k in bank_found or k in raw_text for k in bank_keywords):
                errors.append("ธนาคารที่โอนไม่อยู่ในรายการที่รองรับ")

    # 6. ชื่อผู้รับ — ข้ามถ้า SlipOK verify ผ่าน (SlipOK truncate displayName ทำให้ check ไม่เจอ)
    if not using_slipok and settings.expected_recipient_name:
        expected = settings.expected_recipient_name.strip().lower()
        recipient_name = (slip.get("recipient_name") or "").strip().lower()
        if expected not in recipient_name and expected not in raw_text:
            errors.append(f"ชื่อผู้รับไม่ตรง (ต้องเป็น '{settings.expected_recipient_name}')")

    # set หลังจาก check เสร็จ — ไม่ set reference ถ้าซ้ำ (กัน IntegrityError ตอน commit)
    ref_is_dup = any("สลิปนี้เคยใช้" in e for e in errors)
    payment.amount = str(int(ocr_amount)) if ocr_amount is not None else None
    if not ref_is_dup:
        payment.reference = ocr_reference
    payment.recipient = ocr_recipient

    # ── ผลลัพธ์ ─────────────────────────────────────────────
    if errors:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "ตรวจสลิปไม่ผ่าน",
                "errors": errors,
                "ocr_amount": ocr_amount,
                "ocr_reference": slip["reference"],
                "ocr_recipient": slip["recipient"],
                "expected_amount": expected_amount,
                "expected_account": settings.expected_account,
            },
        )

    payment.verified = True
    payment.verified_at = datetime.now(timezone.utc)
    job.status = JobStatus.queued
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "ตรวจสลิปไม่ผ่าน",
                "errors": ["สลิปนี้เคยใช้กับ job อื่นแล้ว (reference ซ้ำ)"],
                "ocr_reference": slip["reference"],
            },
        )

    # Extend TTL ของ NID/PWD ใน Redis — กันหมดเวลาก่อน worker หยิบงาน
    try:
        redis = get_redis()
        await redis.expire(f"job:{job.id}:nid", 7200)
        await redis.expire(f"job:{job.id}:pwd", 7200)
    except Exception:
        pass

    from app.worker.tasks import run_automation
    run_automation.delay(str(job.id))

    return payment


@router.get("/{job_id}", response_model=PaymentOut)
async def get_payment(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Payment).where(Payment.job_id == job_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลการชำระเงิน")
    return payment
