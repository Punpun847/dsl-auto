"""Intercept ทุก request เมื่อเปิด /exam/post-test เพื่อหา API ที่ load questions"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()
        info = await client.page.evaluate(
            f'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/{course_id}",{{credentials:"include"}})).json()'
        )
        eid = info.get('enroll_id')

        captured = []
        async def on_resp(r):
            if 'elearning.set.or.th' not in r.url:
                return
            captured.append({'method': r.request.method, 'url': r.url, 'status': r.status})

        client.page.on('response', on_resp)

        url = f'https://elearning.set.or.th/SETStudentLoan/enroll/{eid}/exam/post-test'
        print(f'GOTO: {url}\n')
        await client.page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await client.page.wait_for_timeout(8000)

        # หา radio ใน document ทั้งหมด (รวม iframe)
        result = await client.page.evaluate("""() => {
            const root = document.querySelectorAll('input[type="radio"]').length;
            const iframes = document.querySelectorAll('iframe').length;
            const hasForm = document.querySelectorAll('form').length;
            const isLoading = document.body.innerText.includes('Loading');
            return {root, iframes, hasForm, isLoading,
                bodyLength: document.body.innerHTML.length,
                title: document.title,
            };
        }""")
        print(f'page state: {result}\n')

        print('=== Network calls ===')
        api_calls = [c for c in captured if '/api/' in c['url']]
        for c in api_calls:
            print(f'  [{c["status"]}] {c["method"]} {c["url"][:100]}')


if __name__ == '__main__':
    asyncio.run(main())
