"""List courses ที่ user ลงทะเบียน + status"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd = sys.argv[1], sys.argv[2]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        # ลอง list ทั้งหมดจาก /courses
        await client.page.goto('https://elearning.set.or.th/SETStudentLoan/courses',
                                wait_until='domcontentloaded', timeout=30000)
        await client.page.wait_for_timeout(5000)
        items = await client.page.evaluate("""() => {
            const out = new Set();
            document.querySelectorAll('a[href*="/courses/"]').forEach(a => {
                const m = a.href.match(/\\/courses\\/(\\d+)/);
                if (m) out.add(m[1]);
            });
            return [...out];
        }""")
        print(f'unique course IDs: {len(items)}')
        # check first 20 — เลือกที่ enroll_id != null  + cert == null
        for cid in items[:30]:
            try:
                info = await client.page.evaluate(
                    f'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/{cid}",{{credentials:"include"}})).json()'
                )
                title = (info.get('title') or '')[:35]
                eid = info.get('enroll_id')
                print(f'  {cid:>5}  eid={str(eid):>10}  {title}')
            except Exception as e:
                print(f'  {cid:>5}  ERR: {e}')


if __name__ == '__main__':
    asyncio.run(main())
