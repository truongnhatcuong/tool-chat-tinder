"""Automated inspection script to examine Tinder Recs, dismiss cookies, and find like/pass buttons."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEBUG_DIR = Path("debug")
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
HTML_DIR = DEBUG_DIR / "html"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    print("Launching persistent Chromium...")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./data/tinder_browser",
            headless=False,
            viewport={"width": 1280, "height": 840},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ],
            ignore_default_args=["--enable-automation"]
        )

        page = context.pages[0] if context.pages else await context.new_page()
        print("Navigating to https://tinder.com/app/recs...")
        await page.goto("https://tinder.com/app/recs", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(4.0)

        # 1. Dismiss cookie banner if present
        cookie_selectors = [
            "button:has-text('Tôi chấp nhận')",
            "button:has-text('I accept')",
            "button:has-text('Accept')",
            "div[role='dialog'] button:has-text('chấp nhận')",
            "div:has-text('Chúng tôi tôn trọng quyền riêng tư') button"
        ]
        for sel in cookie_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                print(f"Found cookie consent button with '{sel}', clicking...")
                try:
                    await loc.first.click()
                    await asyncio.sleep(2.0)
                    break
                except Exception as e:
                    print(f"Click cookie error: {e}")

        # 2. Check for notifications / location permission dialogs
        dialog_dismiss_selectors = [
            "button:has-text('Không phải bây giờ')",
            "button:has-text('Not now')",
            "button:has-text('Bỏ qua')",
            "button:has-text('Tôi đồng ý')",
            "button:has-text('I agree')"
        ]
        for sel in dialog_dismiss_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                print(f"Found dialog dismiss button '{sel}', clicking...")
                try:
                    await loc.first.click()
                    await asyncio.sleep(1.0)
                except Exception:
                    pass

        # 3. Take updated screenshot and save HTML
        await page.screenshot(path=str(SCREENSHOTS_DIR / "tinder_recs_active.png"))
        html = await page.content()
        with open(HTML_DIR / "tinder_recs_active.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Screenshot saved to debug/screenshots/tinder_recs_active.png")

        # 4. Search for key Recs elements:
        # - Like button
        # - Pass/Nope button
        # - Super like
        # - Rec profile name, age, bio
        elements_to_find = {
            "Like Button": [
                "button[aria-label*='Like']",
                "button[aria-label*='Thích']",
                "[data-testid='gamepad-like']",
                "button:has(svg path[d*='M12 21.35'])"
            ],
            "Pass Button": [
                "button[aria-label*='Pass']",
                "button[aria-label*='Không thích']",
                "button[aria-label*='Nope']",
                "[data-testid='gamepad-pass']"
            ],
            "Profile Info Card": [
                "div[class*='recCard']",
                "div[data-testid='recCard']",
                "div[class*='profileCard']",
                "div[aria-label*='profile']"
            ],
            "Matches Sidebar Tab": [
                "button[aria-label*='Matches']",
                "button[aria-label*='Tương hợp']",
                "a[href*='/app/messages']",
                "div[role='tablist']"
            ]
        }

        print("\n=== DOM SELECTOR PROBE RESULTS ===")
        for name, selectors in elements_to_find.items():
            matched = False
            for s in selectors:
                c = await page.locator(s).count()
                if c > 0:
                    print(f"[FOUND] {name}: '{s}' (count={c})")
                    matched = True
                    break
            if not matched:
                print(f"[NOT FOUND] {name}")

        await context.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
