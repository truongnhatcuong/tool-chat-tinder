"""High level Tinder browser automation wrapper."""
import re
from playwright.async_api import Page
from browser.manager import BrowserManager
from browser.dom_inspector import DOMInspector
from utils.logger import logger


class TinderBrowser:
    """Wrapper coordinating browser interactions, navigation, and DOM state."""

    def __init__(self, manager: BrowserManager):
        self.manager = manager
        self._inspector: DOMInspector | None = None

    @property
    def page(self) -> Page | None:
        return self.manager.page

    def get_inspector(self) -> DOMInspector:
        if not self._inspector and self.page:
            self._inspector = DOMInspector(self.page)
        assert self._inspector is not None
        return self._inspector

    def get_current_conversation_id(self) -> str | None:
        """Extract conversation identifier from current URL e.g. /app/messages/{id}."""
        if not self.page or self.page.is_closed():
            return None
        url = self.page.url
        match = re.search(r"/app/messages/([a-zA-Z0-9_\-]+)", url)
        if match:
            return match.group(1)
        return None

    async def open_conversation(self, conversation_id_or_match_id: str) -> bool:
        """Navigate to or click the target conversation."""
        if not self.page or self.page.is_closed():
            return False
        
        target_url = f"https://tinder.com/app/messages/{conversation_id_or_match_id}"
        if self.page.url == target_url:
            return True
        
        try:
            logger.info(f"Navigating to conversation {conversation_id_or_match_id}...")
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            return True
        except Exception as e:
            logger.warning(f"Failed to navigate to conversation: {e}")
            return False
