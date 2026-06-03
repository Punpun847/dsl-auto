import uuid

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, unique=True)
    slip_path = Column(String(512), nullable=False)
    amount = Column(String(10), nullable=True)              # ยอดที่ OCR อ่านได้
    reference = Column(String(64), nullable=True, unique=True, index=True)   # เลขอ้างอิงสลิป
    recipient = Column(String(32), nullable=True)           # เลขบัญชีปลายทาง
    verified = Column(Boolean, default=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="payment")
