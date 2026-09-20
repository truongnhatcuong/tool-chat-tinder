"""Full automation campaign: Auto-Swipe until out of likes + Auto-Opener for new matches."""
import argparse
import asyncio
import sys
from playwright.async_api import async_playwright
from browser.auto_swipe import AutoSwipeEngine
from browser.match_opener import MatchOpenerEngine
from services.opener_service import OpenerService
from config.settings import get_settings
from database.db import init_db
from utils.logger import logger

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    parser = argparse.ArgumentParser(description="Tinder Auto-Swipe & Auto-Opener Campaign")
    parser.add_argument("--send", action="store_true", help="Disable Dry Run and send live messages")
    parser.add_argument("--skip-swipe", action="store_true", help="Skip swiping and only run openers")
    parser.add_argument("--skip-opener", action="store_true", help="Only swipe, do not run openers")
    parser.add_argument("--max-swipes", type=int, default=150, help="Max cards to swipe")
    args = parser.parse_args()

    settings = get_settings()
    if args.send:
        settings.dry_run = False
        logger.warning("LIVE SENDING MODE ENABLED! Messages will be sent to real matches.")
    else:
        settings.dry_run = True
        logger.info("DRY RUN MODE ENABLED. To send real messages, add --send flag.")

    # Initialize DB schema
    await init_db()

    logger.info("Launching Playwright persistent Chromium...")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=settings.browser.profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 840},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            ignore_default_args=["--enable-automation"]
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Step 1: Auto-Swipe until out of likes
        if not args.skip_swipe:
            logger.info("\n>>> BẮT ĐẦU GIAI ĐOẠN 1: TỰ ĐỘNG QUẸT (LIKE) ĐẾN KHI HẾT LƯỢT <<<")
            swipe_engine = AutoSwipeEngine(page)
            swipe_results = await swipe_engine.run(max_swipes=args.max_swipes)
            logger.info(f"Kết quả quẹt: {swipe_results}")
            await asyncio.sleep(2.0)

        # Step 2: Auto-Opener for all matches without messages
        if not args.skip_opener:
            logger.info("\n>>> BẮT ĐẦU GIAI ĐOẠN 2: TỰ ĐỘNG MỞ LỜI THẢ THÍNH TINH TẾ CHO MATCH MỚI <<<")
            opener_service = OpenerService()
            opener_engine = MatchOpenerEngine(page, opener_service)
            openers_sent = await opener_engine.run_openers_on_all_new_matches(max_openers=10)
            logger.info(f"Tổng số câu mở lời đã xử lý: {openers_sent}")

        logger.info("\n================ CHIẾN DỊCH HOÀN TẤT ================")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
