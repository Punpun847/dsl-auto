"""ดู progress ของ user — courses ไหนที่ enrolled / ทำเสร็จ / มี cert / ยังไม่ทำ"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd = sys.argv[1], sys.argv[2]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        # fetch_courses รวม goto_set ด้วยอยู่แล้ว ไม่ต้องเรียกซ้ำ
        courses = await client.fetch_courses()
        print(f'\nTotal courses available: {len(courses)}\n')

        # แยกตาม status
        cats = {'cert_done': [], 'in_progress': [], 'not_enrolled': []}
        for c in courses:
            st = c.get('status') or 'not_enrolled'
            if st == 'in_progress':
                cats['in_progress'].append(c)
            elif st == 'cert_done' or c.get('certificate_datetime'):
                cats['cert_done'].append(c)
            else:
                cats['not_enrolled'].append(c)

        for cat, items in cats.items():
            print(f'=== {cat} ({len(items)}) ===')
            for c in items[:25]:
                print(f'  {c.get("id"):>5}  {(c.get("title") or "")[:55]}')
            if len(items) > 25:
                print(f'  ... +{len(items)-25} more')
            print()


if __name__ == '__main__':
    asyncio.run(main())
