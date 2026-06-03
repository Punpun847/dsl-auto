from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PaymentOut(BaseModel):
    id: UUID
    job_id: UUID
    amount: Optional[str]
    reference: Optional[str]
    recipient: Optional[str]
    verified: bool
    verified_at: Optional[datetime]

    model_config = {"from_attributes": True}
