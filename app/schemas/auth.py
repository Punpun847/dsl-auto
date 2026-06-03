from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: str
    is_admin: bool
    has_dsl_credentials: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DSLCredentialIn(BaseModel):
    nid: str
    pwd: str

    @field_validator("nid")
    @classmethod
    def validate_nid(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 13:
            raise ValueError("NID ต้องมี 13 หลัก")
        total = sum(int(digits[i]) * (13 - i) for i in range(12))
        if (11 - total % 11) % 10 != int(digits[12]):
            raise ValueError("NID checksum ไม่ถูกต้อง")
        return digits
