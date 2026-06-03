import hashlib
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.utils.redis_client import get_redis
from app.worker.dsl_client import DSLClient, PRICE_PER_HOUR

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _nid_cache_key(nid: str) -> str:
    """Hash NID เป็น key สำหรับ Redis (ไม่เก็บ NID raw)"""
    h = hashlib.sha256(nid.encode()).hexdigest()
    return f"courses:nid:{h}"


class FetchCoursesRequest(BaseModel):
    nid: str
    pwd: str

    @field_validator("nid")
    @classmethod
    def validate_nid(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 13:
            raise ValueError("เลขบัตรประชาชนต้อง 13 หลัก")
        total = sum(int(digits[i]) * (13 - i) for i in range(12))
        if (11 - total % 11) % 10 != int(digits[12]):
            raise ValueError("เลขบัตรประชาชนไม่ถูกต้อง")
        return digits


class CourseOut(BaseModel):
    id: str
    title: str
    hours: float
    price: int
    code: Optional[str] = None
    status: Optional[str] = None   # "not_enrolled" | "not_started" | "in_progress"
    enroll_id: Optional[int] = None
    progress: Optional[float] = None


@router.post("/fetch", response_model=List[CourseOut])
@limiter.limit("3/minute;20/hour")
async def fetch_courses(request: Request, req: FetchCoursesRequest):
    """
    Login เข้า DSL portal ด้วย credentials ของ user
    แล้วดึงหลักสูตรที่ยังไม่ได้ทำพร้อมจำนวนชั่วโมง
    ราคา = ชั่วโมง × 3 บาท

    Rate limited: 3/นาที, 20/ชม. ต่อ IP — กัน DDoS Playwright browser
    """
    async with DSLClient() as client:
        ok = await client.login(req.nid, req.pwd)
        if not ok:
            raise HTTPException(
                status_code=401,
                detail="Login ไม่สำเร็จ — กรุณาตรวจสอบเลขบัตรและรหัสผ่าน",
            )

        courses = await client.fetch_courses()
        if not courses:
            raise HTTPException(
                status_code=404,
                detail="ไม่พบหลักสูตรที่ต้องทำ — คุณอาจทำครบทุกหลักสูตรแล้ว",
            )

        # Cache ผลลัพธ์ใน Redis 1 ชม. — ใช้ใน create_job verify total_price server-side
        try:
            redis = get_redis()
            await redis.setex(
                _nid_cache_key(req.nid),
                3600,
                json.dumps({str(c["id"]): float(c["hours"]) for c in courses}),
            )
        except Exception:
            pass

        return courses


@router.get("/price-rate")
async def price_rate():
    return {"baht_per_hour": PRICE_PER_HOUR}
