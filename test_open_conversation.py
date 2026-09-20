"""Test opening a conversation to inspect chat input, messages, and profile."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEBUG_DIR = Path("debug")
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
HTML_DIR = DEBUG_DIR / "html"


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./data/tinder_browser",
            headless=False,
            viewport={"width": 1280, "height": 840}
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Navigate to first match
        first_match_url = "https://tinder.com/app/messages/64a70182013c330100f198e86792a2aacc55a38ff7957e1a"
        print(f"Navigating to match: {first_match_url}...")
        await page.goto(first_match_url, wait_until="networkidle", timeout=25000)
        await asyncio.sleep(4.0)

        # Screenshot conversation view
        await page.screenshot(path=str(SCREENSHOTS_DIR / "tinder_chat_view.png"))
        print("Saved debug/screenshots/tinder_chat_view.png")

        # Dump HTML
        html = await page.content()
        with open(HTML_DIR / "tinder_chat_view.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved debug/html/tinder_chat_view.html")

        # Find textarea / chat input / send button
        inputs = page.locator("textarea, div[contenteditable='true'], [role='textbox']")
        c_in = await inputs.count()
        print(f"Chat input candidates found: {c_in}")
        for i in range(c_in):
            el = inputs.nth(i)
            tag = await el.evaluate("e => e.tagName.toLowerCase()")
            placeholder = await el.get_attribute("placeholder") or ""
            print(f"  Input #{i}: <{tag}> placeholder='{placeholder}'")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
