import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    type = Column(String(10), nullable=False)               # "ok", "sys", "play", "done", "err"
    message = Column(String(512), nullable=False)
    progress = Column(String(5), nullable=True)             # "73" = 73%
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="logs")
