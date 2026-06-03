from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class JobCreate(BaseModel):
    nid: str
    pwd: str
    courses: List[str]
    total_price: str
    total_hours: str

    @field_validator("nid")
    @classmethod
    def validate_nid(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 13:
            raise ValueError("NID ต้องมี 13 หลัก")
        # checksum
        total = sum(int(digits[i]) * (13 - i) for i in range(12))
        if (11 - total % 11) % 10 != int(digits[12]):
            raise ValueError("NID ไม่ถูกต้อง")
        return digits

    @field_validator("courses")
    @classmethod
    def validate_courses(cls, v: List[str]) -> List[str]:
        if len(v) == 0:
            raise ValueError("ต้องเลือกอย่างน้อย 1 หลักสูตร")
        cleaned = [str(c).strip() for c in v if str(c).strip()]
        if not cleaned:
            raise ValueError("course id ว่าง")
        # dedupe — กัน user เลือกซ้ำแล้ว trigger SET anti-cheat
        cleaned = list(dict.fromkeys(cleaned))
        if len(cleaned) > 50:
            raise ValueError("เลือกได้สูงสุด 50 หลักสูตรต่องาน")
        return cleaned

    @field_validator("total_price")
    @classmethod
    def validate_price(cls, v: str) -> str:
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise ValueError("total_price ต้องเป็นตัวเลข")
        # อนุญาต 0 สำหรับ FREE_MODE — backend จะตัดสินใจอีกครั้ง
        if n < 0:
            raise ValueError("total_price ต้องไม่เป็นลบ")
        if n > 1_000_000:
            raise ValueError("total_price เกินขีดจำกัด")
        return str(int(n)) if n == int(n) else str(n)

    @field_validator("total_hours")
    @classmethod
    def validate_hours(cls, v: str) -> str:
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise ValueError("total_hours ต้องเป็นตัวเลข")
        if n <= 0 or n > 10_000:
            raise ValueError("total_hours ไม่ถูกต้อง")
        return v


class JobLogOut(BaseModel):
    type: str
    message: str
    progress: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    status: str
    courses: List[str]
    total_price: str
    total_hours: str
    created_at: datetime
    completed_at: Optional[datetime]
    logs: List[JobLogOut] = []

    model_config = {"from_attributes": True}
