import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    course_id = Column(String(20), nullable=False)          # "anti", "fin", ...
    pdf_path = Column(String(512), nullable=True)           # path PDF วุฒิบัตร
    issued_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="certificates")
