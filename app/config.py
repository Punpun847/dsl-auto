import logging
import os
import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://gyso:gyso1234@localhost:5432/gyso_db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-this-to-a-random-secret-key"
    # แยก key สำหรับ JWT sign กับ password encryption — ถ้าไม่ตั้ง fall back ไป secret_key
    # (backward compat: prod สมัยก่อนใช้ secret_key อย่างเดียว)
    jwt_secret: str = ""
    enc_key: str = ""
    upload_dir: str = "./uploads"
    admin_password: str = "admin1234"
    expected_account: str = "099-XXX-XXX-4"   # เลขบัญชี/พร้อมเพย์ของบริษัท (4 ตัวสุดท้าย)
    expected_recipient_name: str = ""         # ชื่อผู้รับ (substring) — เว้นว่างถ้าไม่เช็ค
    expected_bank_keywords: str = "กสิกร,ไทยพาณิชย์,กรุงเทพ,กรุงไทย,กรุงศรี,ออมสิน,นาคิน,ภัทร,ทหารไทย,ttb,scb,kbank,kkp,bbl,ktb,bay,gsb"
    slip_max_age_minutes: int = 30            # สลิปต้องสร้างไม่เกิน X นาที (0 = ปิด check)
    jwt_algorithm: str = "HS256"
    access_token_expire_hours: int = 24
    slipok_api_key: str = ""
    slipok_branch_id: str = ""
    claude_api_key: str = ""
    deepseek_api_key: str = ""

    # CORS — comma-separated origins (ใช้ "*" เฉพาะ dev เท่านั้น)
    cors_origins: str = "*"
    # production flag — ถ้า true จะ raise error ถ้าใช้ default secrets
    is_production: bool = False
    # FREE_MODE — ปิดระบบชำระเงิน, user ใช้ฟรี (เก็บข้อมูล/launch ช่วงแรก)
    # หากเปิดให้ใช้ฟรี: backend จะ auto-verify payment, frontend ซ่อน step ชำระเงิน
    # เปิดใช้งานระบบจ่ายเงินอีกครั้ง: ตั้ง FREE_MODE=false ใน .env
    free_mode: bool = False

    # ── DSL automation tuning ─────────────────────────────────────
    # VIDEO_SPEED: เร่งวิดีโอ — สูงไปอาจตรง anti-cheat ของ SET (16x ใช้งานได้ปกติ)
    dsl_video_speed: int = 16
    # MAX_ATTEMPTS: จำนวนครั้ง submit exam สูงสุด — เกิน 3 ทำให้ SET ตั้ง certificate=False
    dsl_max_exam_attempts: int = 3
    # WATCH_TIMEOUT_SEC: safety cap ต่อคลิป (วินาที) — กันค้าง > 30 นาที
    dsl_watch_timeout_sec: int = 60 * 30
    # HUMAN_ANSWER_TIMEOUT: รอ user ตอบ exam ผ่าน dashboard (วินาที)
    dsl_human_answer_timeout: int = 600

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

    def get_cors_origins(self) -> list[str]:
        if not self.cors_origins or self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()


# Helper: ใช้ jwt_secret/enc_key ถ้าตั้งไว้ ไม่งั้น fall back secret_key
def get_jwt_secret() -> str:
    return settings.jwt_secret or settings.secret_key


def get_enc_key() -> str:
    return settings.enc_key or settings.secret_key


# Production guard: ห้ามใช้ default secrets
_DEFAULT_SECRET = "change-this-to-a-random-secret-key"
_DEFAULT_ADMIN_PWD = "admin1234"

if settings.is_production:
    if settings.secret_key == _DEFAULT_SECRET or "change-this" in settings.secret_key.lower():
        raise RuntimeError(
            "SECRET_KEY ยังเป็นค่า default — ตั้งใน .env ก่อน deploy production"
        )
    if settings.admin_password == _DEFAULT_ADMIN_PWD or len(settings.admin_password) < 12:
        raise RuntimeError(
            "ADMIN_PASSWORD ยังเป็น default หรือสั้นเกินไป — ตั้งให้มากกว่า 12 chars"
        )
elif settings.secret_key == _DEFAULT_SECRET:
    warnings.warn(
        "⚠️  SECRET_KEY ใช้ค่า default — โปรเจกต์นี้ไม่ปลอดภัย ตั้งใน .env ก่อนใช้จริง",
        RuntimeWarning,
        stacklevel=2,
    )
