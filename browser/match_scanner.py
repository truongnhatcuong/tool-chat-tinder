"""Match Scanner scanning the sidebar for matches and conversations."""
import asyncio
import re
from typing import Callable, Coroutine, Any
from playwright.async_api import Page
from browser.selectors import get_selector
from utils.logger import logger


class MatchScanner:
    """Scans Tinder sidebar to discover matches and unread conversations."""

    def __init__(self, page: Page):
        self.page = page
        self._is_running = False

    async def scan_matches_once(self) -> list[dict[str, Any]]:
        """Perform one pass over the matches/conversations list in the DOM."""
        if not self.page or self.page.is_closed():
            return []

        # Auto-dismiss any popups that might overlay the sidebar
        try:
            from browser.popup_handler import dismiss_blocking_popups
            await dismiss_blocking_popups(self.page)
        except Exception:
            pass

        results = []
        try:
            # Look for conversation link items: a[href*='/app/messages/']
            items = self.page.locator("a[href*='/app/messages/']")
            count = await items.count()
            
            for i in range(count):
                item = items.nth(i)
                href = await item.get_attribute("href") or ""
                match_id = ""
                m = re.search(r"/app/messages/([a-zA-Z0-9_\-]+)", href)
                if m:
                    match_id = m.group(1)

                if not match_id:
                    continue

                # Extract name
                name = ""
                text_content = await item.inner_text()
                lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                if lines:
                    name = lines[0]

                # Check unread indicator
                has_unread = False
                badge = item.locator("span[class*='badge'], [data-testid='unread-indicator']")
                if await badge.count() > 0:
                    has_unread = True

                results.append({
                    "tinder_id": match_id,
                    "conversation_id": match_id,
                    "name": name or "Match",
                    "has_unread": has_unread
                })

        except Exception as e:
            logger.warning(f"Error during match scan: {e}")

        return results

    async def run_loop(
        self,
        interval_seconds: float,
        on_matches_found: Callable[[list[dict]], Coroutine[Any, Any, None]]
    ):
        """Continuously scan for matches at specified interval."""
        self._is_running = True
        logger.info(f"Started Match Scanner loop (interval={interval_seconds}s)")
        while self._is_running:
            try:
                matches = await self.scan_matches_once()
                if matches:
                    await on_matches_found(matches)
            except Exception as e:
                logger.warning(f"Match scanner loop iteration error: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._is_running = False
        logger.info("Match Scanner stopped.")
