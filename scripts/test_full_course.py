"""ทำคอร์สครบ — mark topics + exam + ขอ cert (full pipeline)"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    cert_dir = Path(f"/tmp/test_cert_{course_id}")
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        async def on_log(t, m, p=None):
            print(f"[{t:5}] {m}" + (f"  ({p}%)" if p else ""))

        pdf = await client.complete_course_via_api(
            course_id=course_id,
            on_log=on_log,
            cert_dir=cert_dir,
        )
        print(f"\n📄 PDF path: {pdf}")
        if pdf:
            print(f"📦 size: {Path(pdf).stat().st_size:,} bytes")


if __name__ == "__main__":
    asyncio.run(main())
