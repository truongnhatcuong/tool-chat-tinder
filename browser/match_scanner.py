"""Match Scanner scanning the sidebar for matches and conversations."""
import asyncio
import re
from typing import Callable, Coroutine, Any
from playwright.async_api import Page
from browser.selectors import get_selector
from utils.logger import logger


class MatchScanner:
    """Scans Tinder sidebar to discover matches and unread conversations."""

    def __init__(
        self,
        page: Page,
        operation_lock: asyncio.Lock | None = None,
        can_switch_tabs: Callable[[], bool] | None = None,
    ):
        self.page = page
        self.operation_lock = operation_lock or asyncio.Lock()
        self.can_switch_tabs = can_switch_tabs or (lambda: True)
        self._is_running = False

    def _sidebar_tab(self, tab_name: str):
        """Return a locator for Tinder's localized Matches/Messages tab."""
        labels = {
            "matches": ("Matches", "Tương hợp"),
            "messages": ("Messages", "Tin nhắn"),
        }
        selectors = [
            f"button[role='tab']:has-text('{label}')"
            for label in labels[tab_name]
        ]
        return self.page.locator(", ".join(selectors))

    async def _activate_sidebar_tab(self, tab_name: str) -> bool:
        """Select one sidebar tab and wait for its virtualized panel to render."""
        try:
            tabs = self._sidebar_tab(tab_name)
            if await tabs.count() == 0:
                logger.debug(f"Sidebar tab not found: {tab_name}")
                return False
            tab = tabs.first
            if await tab.get_attribute("aria-selected") != "true":
                await tab.click()
                await asyncio.sleep(0.8)
            return await tab.get_attribute("aria-selected") == "true"
        except Exception as e:
            logger.debug(f"Sidebar tab switch notice ({tab_name}): {e}")
            return False

    async def ensure_messages_tab_active(self) -> None:
        """Restore the Messages tab after discovering new matches."""
        await self._activate_sidebar_tab("messages")

    async def _collect_visible_links(self, source_tab: str) -> list[dict[str, Any]]:
        """Collect conversation links rendered by the currently selected tab."""
        results: list[dict[str, Any]] = []
        items = self.page.locator("a[href*='/app/messages/']")
        count = await items.count()

        for i in range(count):
            item = items.nth(i)
            href = await item.get_attribute("href") or ""
            match = re.search(r"/app/messages/([a-zA-Z0-9_\-]+)", href)
            if not match:
                continue

            match_id = match.group(1)
            name = ""
            aria_label = await item.get_attribute("aria-label")
            if aria_label:
                name = aria_label.split(".")[0].replace("Start chat", "").strip()

            if not name or name == "New Match":
                text_content = await item.inner_text()
                lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                if lines:
                    name = lines[0]

            badge = item.locator(
                "span[class*='badge'], [data-testid='unread-indicator'], "
                "[aria-label='New Match'], [aria-label='Tương hợp mới'], "
                "[aria-label='New Message'], [aria-label='Tin nhắn mới']"
            )
            results.append({
                "tinder_id": match_id,
                "conversation_id": match_id,
                "name": name or "Match",
                "has_unread": await badge.count() > 0,
                "source_tab": source_tab,
            })

        return results

    async def scan_matches_once(self) -> list[dict[str, Any]]:
        """Scan both virtualized sidebar tabs and merge people by Tinder ID."""
        if not self.page or self.page.is_closed():
            return []

        try:
            from browser.popup_handler import dismiss_blocking_popups
            await dismiss_blocking_popups(self.page)
        except Exception:
            pass

        collected: list[dict[str, Any]] = []
        try:
            if self.can_switch_tabs():
                if await self._activate_sidebar_tab("matches"):
                    matches = await self._collect_visible_links("matches")
                    collected.extend(matches)
                    if matches:
                        logger.info(f"Discovered {len(matches)} person(s) in Matches tab.")

                # Always restore Messages so active conversations remain available
                # to the AUTO round-robin and message monitor.
                if await self._activate_sidebar_tab("messages"):
                    collected.extend(await self._collect_visible_links("messages"))
            else:
                # A conversation owns the full turn (debounce -> AI -> send).
                # Read only what Tinder already renders; never change sidebar tabs.
                collected.extend(await self._collect_visible_links("current"))
        except Exception as e:
            logger.warning(f"Error during match scan: {e}")

        merged: dict[str, dict[str, Any]] = {}
        for item in collected:
            tinder_id = item["tinder_id"]
            existing = merged.get(tinder_id)
            if existing is None:
                merged[tinder_id] = item
                continue
            existing["has_unread"] = existing["has_unread"] or item["has_unread"]
            if existing["name"] == "Match" and item["name"] != "Match":
                existing["name"] = item["name"]
            if item["source_tab"] == "messages":
                existing["source_tab"] = "messages"

        return list(merged.values())

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
                async with self.operation_lock:
                    matches = await self.scan_matches_once()
                if matches:
                    await on_matches_found(matches)
            except Exception as e:
                logger.warning(f"Match scanner loop iteration error: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._is_running = False
        logger.info("Match Scanner stopped.")
