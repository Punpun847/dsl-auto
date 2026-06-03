"""Smoke test FREE_MODE — 2-step wizard + summary panel ที่บอก 'ฟรี'"""
import os
from playwright.sync_api import sync_playwright

out = os.path.abspath("./screenshots")
os.makedirs(out, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    # 1. Logged-out form view — แสดง banner + 2-step indicator
    page.goto("http://127.0.0.1:8000/", wait_until="networkidle", timeout=20000)
    page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{out}/10_free_logged_out.png", full_page=False)
    print("1/2 logged-out + free_mode")

    # 2. Login + check 2-step view
    page.get_by_role("button", name="เข้าสู่ระบบ / สมัครสมาชิก").click()
    page.wait_for_timeout(600)
    modal = page.locator("div.fixed.inset-0.z-50")
    modal.locator('div.flex.bg-paper-1 button:has-text("สมัครสมาชิก")').click()
    page.wait_for_timeout(400)
    import time
    modal.locator('input[type=email]').fill(f"free-{int(time.time())}@test.com")
    modal.locator('input[type=password]').nth(0).fill("password123")
    modal.locator('input[type=password]').nth(1).fill("password123")
    modal.locator('form button[type=submit]').click()
    page.wait_for_timeout(4000)

    page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
    page.wait_for_timeout(800)
    page.screenshot(path=f"{out}/11_free_logged_in.png", full_page=False)
    print("2/2 logged-in 2-step wizard")

    b.close()
