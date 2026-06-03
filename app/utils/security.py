import hashlib
import os
import uuid
from base64 import b64encode, b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt

from app.config import get_enc_key, get_jwt_secret, settings


def hash_nid(nid: str) -> str:
    return hashlib.sha256(nid.encode()).hexdigest()


def _derive_key() -> bytes:
    return hashlib.sha256(get_enc_key().encode()).digest()  # 32 bytes → AES-256


def encrypt_password(pwd: str) -> str:
    key = _derive_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, pwd.encode(), None)
    return b64encode(nonce + ct).decode()


def decrypt_password(token: str) -> str:
    key = _derive_key()
    raw = b64decode(token.encode())
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.access_token_expire_hours)
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": expire,
            "jti": uuid.uuid4().hex,
        },
        get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
