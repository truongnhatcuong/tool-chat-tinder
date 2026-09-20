"""Auto-Swipe engine: automatically likes cards until likes are exhausted."""
import asyncio
import random
import re
from typing import Callable, Coroutine, Any
from playwright.async_api import Page
from utils.logger import logger


class AutoSwipeEngine:
    """Automates liking cards on https://tinder.com/app/recs until likes run out."""

    def __init__(self, page: Page):
        self.page = page
        self._is_running = False
        self.total_swiped = 0
        self.total_matches = 0

    async def is_out_of_likes(self) -> bool:
        """Detect whether Tinder's out-of-likes modal is visible."""
        if not self.page or self.page.is_closed():
            return True

        indicators = [
            "div:has-text('Hết lượt thích')",
            "div:has-text('You are out of likes')",
            "div:has-text('Out of Likes')",
            "button:has-text('Mua thêm lượt Thích')",
            "button:has-text('Get Tinder Plus')",
            "button:has-text('Nhận Tinder Gold')"
        ]
        for sel in indicators:
            if await self.page.locator(sel).count() > 0:
                return True
        return False

    async def check_match_modal(self) -> dict | None:
        """Detect if an 'It's a Match' popup is currently shown."""
        match_indicators = [
            "div:has-text('Tương hợp mới!')",
            "div:has-text('It’s a Match!')",
            "div:has-text('Đã tương hợp')",
            "[data-testid='its-a-match']"
        ]
        for sel in match_indicators:
            loc = self.page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                logger.info("New match popup detected on screen!")
                # Find dismiss or keep swiping button
                keep_swiping = self.page.locator(
                    "button:has-text('Tiếp tục quẹt'), button:has-text('Keep Swiping'), button[aria-label*='Close'], button:has-text('Đóng')"
                )
                if await keep_swiping.count() > 0:
                    try:
                        await keep_swiping.first.click()
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass
                return {"is_match": True}
        return None

    async def read_current_card_info(self) -> dict[str, str]:
        """Extract name, age, distance, bio from the top rec card."""
        info = {"name": "", "age": "", "distance": "", "bio": ""}
        try:
            # Name and age typically in heading or card overlay
            name_el = self.page.locator("div[class*='recCard'] h1, [data-testid='recCard'] h1, div[class*='profileCard'] h1")
            if await name_el.count() > 0:
                raw_text = (await name_el.first.inner_text()).strip()
                m = re.search(r"^(.+?)\s*(\d{2})$", raw_text)
                if m:
                    info["name"] = m.group(1).strip()
                    info["age"] = m.group(2)
                else:
                    info["name"] = raw_text

            # Distance
            dist_el = self.page.locator("div:has-text('Cách xa')")
            if await dist_el.count() > 0:
                info["distance"] = (await dist_el.first.inner_text()).strip()
        except Exception as e:
            logger.debug(f"Card info extract note: {e}")

        return info

    async def run(
        self,
        max_swipes: int = 100,
        min_delay: float = 1.8,
        max_delay: float = 3.5,
        on_match_callback: Callable[[dict], Coroutine[Any, Any, None]] | None = None,
        should_stop: Callable[[], bool] | None = None
    ) -> dict[str, int]:
        """
        Start auto-swiping right (Like) until out of likes or max_swipes reached.
        """
        self._is_running = True
        logger.info("================ STARTING AUTO-LIKE SESSION ================")
        
        # Ensure we are on /app/recs
        if "/app/recs" not in self.page.url:
            logger.info("Navigating to https://tinder.com/app/recs...")
            await self.page.goto("https://tinder.com/app/recs", wait_until="domcontentloaded")
            await asyncio.sleep(2.0)

        from browser.popup_handler import dismiss_blocking_popups

        while self._is_running and self.total_swiped < max_swipes:
            if should_stop and should_stop():
                logger.info("Auto-like dừng do Pause/Emergency Stop.")
                break
            # Something else (opener/scanner) may have navigated away: return to recs
            if "/app/recs" not in (self.page.url or ""):
                logger.info("Đã bị chuyển trang, quay lại /app/recs để tiếp tục like...")
                await self.page.goto("https://tinder.com/app/recs", wait_until="domcontentloaded")
                await asyncio.sleep(2.0)

            # 0. Automatically dismiss any blocking popups (e.g. 'Không quan tâm', 'Không phải bây giờ')
            await dismiss_blocking_popups(self.page)

            # 1. Check if out of likes
            if await self.is_out_of_likes():
                logger.warning("ĐÃ HẾT LƯỢT THÍCH (Out of Likes)! Tự động dừng phiên quẹt thẻ.")
                break

            # 2. Check for match popup
            match_data = await self.check_match_modal()
            if match_data:
                self.total_matches += 1
                if on_match_callback:
                    await on_match_callback(match_data)

            # 3. Read current card details
            card_info = await self.read_current_card_info()
            name_label = f"{card_info['name']} ({card_info['age']})" if card_info['name'] else "Card"

            # 4. Human-like natural delay
            delay = random.uniform(min_delay, max_delay)
            logger.info(f"[{self.total_swiped + 1}] Đang thích {name_label}... (Delay {delay:.1f}s)")
            await asyncio.sleep(delay)
            if not self._is_running or (should_stop and should_stop()):
                break

            # 5. Send LIKE via Right Arrow keyboard shortcut (native & reliable)
            await self.page.keyboard.press("ArrowRight")
            self.total_swiped += 1

            # Short settle time
            await asyncio.sleep(0.8)

        logger.info(
            f"Phiên quẹt hoàn tất. Tổng số lượt thích: {self.total_swiped}, Matches mới: {self.total_matches}"
        )
        self._is_running = False
        return {"swiped": self.total_swiped, "matches": self.total_matches}

    def stop(self):
        self._is_running = False
        logger.info("Auto-swipe stopped by user.")
