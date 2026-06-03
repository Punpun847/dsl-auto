import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    async with DSLClient(headless=False) as client:
        await client.login('1100201764358', 'Poonnapob200432')
        await client.goto_set()
        info = await client.page.evaluate(
            'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/1286",{credentials:"include"})).json()'
        )
        eid = info.get('enroll_id')

        # navigate to /exam/post-test และ wait for SPA render
        await client.page.goto(f'https://elearning.set.or.th/SETStudentLoan/enroll/{eid}/exam/post-test',
                                wait_until='domcontentloaded', timeout=30000)
        # รอนาน 15 วินาที + ตรวจสอบทุก 3 วินาที
        for sec in range(15):
            await client.page.wait_for_timeout(2000)
            r = await client.page.evaluate(
                '() => ({url: location.href, radios: document.querySelectorAll("input[type=\'radio\']").length, btnCount: document.querySelectorAll("button").length, btns: Array.from(document.querySelectorAll("button,a.btn,.btn")).map(b=>(b.innerText||"").trim().slice(0,40)).filter(t=>t).slice(0,10)})'
            )
            print(f't={sec*2}s url={r["url"][-50:]} radios={r["radios"]} btns={r["btns"]}')
            if r["radios"] > 0:
                print("HAS RADIOS!")
                break


if __name__ == '__main__':
    asyncio.run(main())
