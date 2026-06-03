import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient, SET_BASE


async def main():
    async with DSLClient(headless=False) as client:
        await client.login("1100201764358", "Poonnapob200432")
        await client.goto_set()
        info = await client.page.evaluate(
            'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/1291",{credentials:"include"})).json()'
        )
        eid = info.get("enroll_id")
        await client.page.goto(
            f"{SET_BASE}/enroll/{eid}/exam/exam",
            wait_until="domcontentloaded", timeout=30000,
        )
        await client.page.wait_for_timeout(10_000)
        r = await client.page.evaluate("""() => ({
            radios: document.querySelectorAll('input[type="radio"]').length,
            btns: Array.from(document.querySelectorAll('button, a.btn, .btn'))
                  .map(b => (b.innerText || '').trim().slice(0, 50))
                  .filter(t => t).slice(0, 15),
            url: location.href,
            text: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 500),
        })""")
        print("URL:", r["url"])
        print("radios:", r["radios"])
        print("buttons:")
        for b in r["btns"]: print(f"  - {b}")
        print()
        print("body:", r["text"])
        await client.page.wait_for_timeout(20_000)


if __name__ == "__main__":
    asyncio.run(main())
