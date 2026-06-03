"""SlipOK slip verification client.

POST https://api.slipok.com/api/line/apikey/{branch_id}
Header: x-authorization: <API_KEY>
Body:   multipart with file field "files" (or "image" — both supported)

Response shape (success):
  {
    "success": true,
    "data": {
        "transRef": "...",
        "transDate": "20260520",
        "transTime": "14:30",
        "transTimestamp": "2026-05-20T07:30:00.000Z",
        "amount": 3.0,
        "sender":   {"displayName": "...", "name": "...", "account": {"value": "x-9765"}},
        "receiver": {"displayName": "...", "name": "...", "account": {"value": "x-4759"}},
        "sendingBank": "002",
        "receivingBank": "025",
        ...
    }
  }

Response shape (failure):
  {"success": false, "code": 1xxx, "message": "..."}
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SLIPOK_BASE = "https://api.slipok.com/api/line/apikey"


async def verify_slip(slip_path: str) -> Optional[Dict[str, Any]]:
    """ส่งสลิปไปให้ SlipOK ตรวจ
    คืน dict normalized:
        {
            "amount": float,
            "reference": str,
            "recipient": str (4 ตัวท้าย),
            "sender": str (4 ตัวท้าย),
            "datetime": datetime,
            "bank_code": str,
            "raw": dict (response เต็ม),
        }
    คืน None ถ้า config ไม่ครบหรือ API error
    """
    if not settings.slipok_api_key or not settings.slipok_branch_id:
        logger.info("SlipOK ไม่ได้ตั้ง API key — ข้าม")
        return None

    url = f"{SLIPOK_BASE}/{settings.slipok_branch_id}"
    headers = {"x-authorization": settings.slipok_api_key}

    try:
        with open(slip_path, "rb") as f:
            file_bytes = f.read()
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                url,
                headers=headers,
                files={"files": (Path(slip_path).name, file_bytes, "image/jpeg")},
            )
        body = res.json()
    except Exception as e:
        logger.warning(f"SlipOK request failed: {e}")
        return None

    if not body.get("success"):
        logger.info(f"SlipOK ปฏิเสธสลิป: code={body.get('code')} msg={body.get('message')}")
        return {"success": False, "code": body.get("code"), "message": body.get("message"), "raw": body}

    d = body.get("data") or {}
    sender_acc = ((d.get("sender") or {}).get("account") or {}).get("value") or ""
    receiver_acc = ((d.get("receiver") or {}).get("account") or {}).get("value") or ""

    def tail4(s: str) -> str:
        return "".join(c for c in s if c.isdigit())[-4:]

    # parse datetime — prefer transTimestamp (ISO), fallback ผสม transDate+transTime
    dt = None
    ts = d.get("transTimestamp")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # SlipOK ส่ง UTC → convert เป็น Asia/Bangkok naive
            from datetime import timedelta, timezone
            dt = (dt.astimezone(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)
        except Exception:
            dt = None
    if not dt and d.get("transDate") and d.get("transTime"):
        try:
            dt = datetime.strptime(f"{d['transDate']} {d['transTime']}", "%Y%m%d %H:%M")
        except Exception:
            dt = None

    return {
        "success": True,
        "amount": float(d.get("amount") or 0),
        "reference": d.get("transRef") or "",
        "recipient": tail4(receiver_acc),
        "sender": tail4(sender_acc),
        "recipient_name": (d.get("receiver") or {}).get("displayName") or (d.get("receiver") or {}).get("name") or "",
        "datetime": dt,
        "bank_code": d.get("receivingBank") or "",
        "raw": d,
    }
