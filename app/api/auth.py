from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User, UserDSLCredential
from app.schemas.auth import DSLCredentialIn, RegisterIn, TokenOut, UserOut
from app.utils.security import (
    create_access_token,
    decode_access_token,
    decrypt_password,
    encrypt_password,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
# auto_error=False — ทำให้ optional auth ไม่ raise 401 ถ้าไม่มี token
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token ไม่ถูกต้องหรือหมดอายุ")
    result = await db.execute(
        select(User)
        .where(User.id == payload["sub"])
        .options(selectinload(User.dsl_credential))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="ไม่พบ user หรือถูก deactivate")
    return user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Return current user if a valid JWT is provided; otherwise None.
    ใช้กับ endpoint ที่รองรับทั้ง anonymous + authenticated"""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    result = await db.execute(
        select(User)
        .where(User.id == payload["sub"])
        .options(selectinload(User.dsl_credential))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    return user


def _build_user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "has_dsl_credentials": user.dsl_credential is not None,
        "created_at": user.created_at,
    }


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email นี้ถูกใช้แล้ว")

    user = User(
        email=body.email.lower(),
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(user, ["dsl_credential"])
    return _build_user_out(user)


@router.post("/login", response_model=TokenOut)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form_data.username.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email หรือรหัสผ่านไม่ถูกต้อง")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account ถูก deactivate")

    token = create_access_token(str(user.id), user.email)
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _build_user_out(current_user)


@router.post("/credentials", response_model=UserOut)
async def save_dsl_credentials(
    body: DSLCredentialIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """บันทึก NID/PWD ของ DSL portal ไว้ใน account — เข้ารหัสด้วย AES-GCM"""
    cred = current_user.dsl_credential
    if cred:
        cred.nid_encrypted = encrypt_password(body.nid)
        cred.pwd_encrypted = encrypt_password(body.pwd)
    else:
        cred = UserDSLCredential(
            user_id=current_user.id,
            nid_encrypted=encrypt_password(body.nid),
            pwd_encrypted=encrypt_password(body.pwd),
        )
        db.add(cred)

    await db.commit()
    await db.refresh(current_user, ["dsl_credential"])
    return _build_user_out(current_user)


@router.delete("/credentials", status_code=204)
async def delete_dsl_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ลบ DSL credentials ที่บันทึกไว้"""
    if current_user.dsl_credential:
        await db.delete(current_user.dsl_credential)
        await db.commit()
