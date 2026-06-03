import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, ForeignKey, String, DateTime, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class JobStatus(PyEnum):
    pending = "pending"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # nullable=True เพื่อ backward-compat กับ jobs ที่สร้างก่อนมี auth
    # ถ้า set แล้ว → ownership check จะ enforce
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    nid_hash = Column(String(64), nullable=False)          # SHA-256 ของ NID
    courses = Column(JSON, nullable=False)                  # ["anti", "fin", ...]
    total_price = Column(String(10), nullable=False)
    total_hours = Column(String(10), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    payment = relationship("Payment", back_populates="job", uselist=False)
    certificates = relationship("Certificate", back_populates="job")
    logs = relationship("JobLog", back_populates="job", order_by="JobLog.created_at")
