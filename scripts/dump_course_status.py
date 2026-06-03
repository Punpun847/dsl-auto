"""ดึง status ทุก course ที่ user เคยเกี่ยวข้อง — including enrolled, completed"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient, SET_LIST_URL


async def main():
    async with DSLClient(headless=True) as client:
        await client.login('1100201764358', 'Poonnapob200432')
        await client.goto_set()

        # ลอง classroom + summary + list
        for path in ['/SETStudentLoan/list',
                     '/SETStudentLoan/classroom',
                     '/SETStudentLoan/']:
            url = f'https://elearning.set.or.th{path}'
            await client.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await client.page.wait_for_timeout(3000)

        # ตอนนี้บน page หลัก — scan ทั้งหน้าหา course IDs
        ids = await client.page.evaluate("""() => {
            const out = new Set();
            document.querySelectorAll('a[href*="/courses/"], a[href*="/enroll/"]').forEach(a => {
                const m = (a.href || '').match(/\\/(?:courses|enroll)\\/(\\d+)/);
                if (m) out.add(m[1]);
            });
            return [...out];
        }""")
        print(f'IDs found: {len(ids)} → {ids}')

        # check status for each
        for cid in ids[:50]:
            r = await client.page.evaluate(
                f"""async () => {{
                    const d = await (await fetch('/api/site/groups/SETStudentLoan/courses/{cid}', {{credentials:'include'}})).json();
                    let pct = null, cert = null;
                    if (d.enroll_id) {{
                        const ed = await (await fetch('/api/site/enroll/' + d.enroll_id, {{credentials:'include'}})).json();
                        pct = ed.learning_percentage;
                        cert = ed.certificate_datetime;
                    }}
                    return {{title: (d.title||'').slice(0,55), enroll_id: d.enroll_id, pct: pct, cert: cert}};
                }}"""
            )
            tag = '✅cert' if r.get('cert') else ('▶️ก้าวหน้า' if r.get('enroll_id') else '❌ยังไม่เริ่ม')
            print(f'  {cid:>5} {tag:<15} pct={str(r.get("pct")):>4}  {r.get("title")}')


if __name__ == '__main__':
    asyncio.run(main())
