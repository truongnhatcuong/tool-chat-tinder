"""Standalone Real Tinder DOM Inspector CLI.
Workflow:
1. Opens real Tinder with persistent profile.
2. Waits for manual login if not logged in.
3. Allows user to open matches/conversation.
4. Performs live DOM inspection and tests all selectors.
5. Saves results to debug/dom_report.json and debug/dom_notes.md.
"""
import asyncio
import sys
from browser.manager import BrowserManager
from browser.dom_inspector import DOMInspector
from utils.logger import logger


async def main():
    logger.info("=== TINDER REAL DOM INSPECTOR TOOL ===")
    mgr = BrowserManager()
    try:
        page = await mgr.start()
        logger.info("Browser launched. Checking login status...")

        is_logged_in = await mgr.check_login_status()
        if not is_logged_in:
            logger.info("=======================================================")
            logger.info("Chưa phát hiện phiên đăng nhập Tinder.")
            logger.info("Vui lòng đăng nhập tài khoản Tinder của bạn trên cửa sổ Chromium vừa mở.")
            logger.info("Tool sẽ tự động phát hiện ngay khi đăng nhập thành công...")
            logger.info("=======================================================")
            
            logged_in = await mgr.wait_for_manual_login(timeout_seconds=300)
            if not logged_in:
                logger.error("Hết thời gian chờ đăng nhập. Vui lòng chạy lại khi đã sẵn sàng.")
                return

        logger.info("Đã phát hiện đăng nhập Tinder thành công!")
        logger.info("=================================================================")
        logger.info("Đang bật chế độ giám sát DOM tự động.")
        logger.info("Bạn có thể tự do bấm vào danh sách Matches hoặc mở cuộc trò chuyện.")
        logger.info("Công cụ sẽ tự động quét, test selector, ghi nhận vào debug/dom_report.json")
        logger.info("và chụp ảnh màn hình debug.")
        logger.info("=================================================================")

        inspector = DOMInspector(page)
        
        from browser.popup_handler import dismiss_blocking_popups

        # Continuous inspection loop: runs every 5 seconds while browser is open
        iteration = 0
        last_url = ""
        while not page.is_closed():
            iteration += 1
            current_url = page.url
            url_changed = (current_url != last_url)
            last_url = current_url

            # Automatically dismiss popup if present (e.g. 'Không quan tâm')
            await dismiss_blocking_popups(page)

            logger.info(f"[Pass #{iteration}] Đang kiểm tra URL: {current_url}")
            report = await inspector.run_full_inspection()
            
            # If matches or chat or profile found, take debug snapshot
            if url_changed:
                await mgr.capture_debug_screenshot(f"dom_step_{iteration}")
                await mgr.save_debug_html(f"dom_step_{iteration}")

            healthy, results = await inspector.perform_health_check()
            logger.info(f"Health check: {'HEALTHY' if healthy else 'PENDING/PARTIAL'}")

            await asyncio.sleep(5.0)

    except Exception as e:
        logger.exception(f"Lỗi trong quá trình inspect DOM: {e}")
    finally:
        logger.info("Hoàn tất phiên kiểm tra.")


if __name__ == "__main__":
    asyncio.run(main())
