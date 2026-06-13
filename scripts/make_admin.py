"""ตั้ง user เป็น admin: python scripts/make_admin.py <email>
ถ้าไม่มี user → สร้างใหม่ (ต้องใส่ password): python scripts/make_admin.py <email> <password>
"""
import asyncio, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'stubs')
from sqlalchemy import select
from app.database import AsyncSessionLocal as async_session
from app.models import User
from app.utils.security import hash_password

async def main():
    if len(sys.argv) < 2:
        print("usage: make_admin.py <email> [password]"); return
    email = sys.argv[1]; pwd = sys.argv[2] if len(sys.argv) > 2 else None
    async with async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not u:
            if not pwd: print("ไม่พบ user — ใส่ password เพื่อสร้างใหม่: make_admin.py <email> <password>"); return
            u = User(email=email, hashed_password=hash_password(pwd), is_admin=True, is_active=True)
            db.add(u); await db.commit(); print(f"✅ สร้าง admin ใหม่: {email}")
        else:
            u.is_admin = True; await db.commit(); print(f"✅ ตั้ง {email} เป็น admin แล้ว")

asyncio.run(main())
