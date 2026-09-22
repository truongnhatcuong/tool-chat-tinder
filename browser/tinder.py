"""High level Tinder browser automation wrapper."""
import asyncio
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

    async def get_chat_dom_signature(self) -> str:
        """Return a compact fingerprint of the currently rendered chat DOM."""
        if not self.page or self.page.is_closed():
            return ""
        try:
            return await self.page.evaluate(r"""() => {
                const section = document.querySelector(
                    "div.chat section, section[class*='Fx($flx2)'], div[role='log']"
                );
                const main = section || document.querySelector('main');
                if (!main) return '';
                const heading = Array.from(document.querySelectorAll('h1, h2'))
                    .map(el => (el.innerText || '').trim())
                    .filter(Boolean)
                    .slice(0, 4)
                    .join('|');
                const text = (main.innerText || '').replace(/\s+/g, ' ').trim();
                return `${heading}::${text}`.slice(0, 4000);
            }""")
        except Exception:
            return ""

    async def wait_for_conversation_ready(
        self,
        conversation_id: str,
        previous_signature: str = "",
        timeout_seconds: float = 8.0,
    ) -> tuple[bool, str]:
        """Wait until the URL and rendered chat both belong to the requested ID.

        Tinder updates the SPA URL before replacing the chat pane.  Merely reading
        the new URL can therefore pair conversation B's ID with conversation A's
        still-rendered bubbles.  When changing chats, require the rendered
        fingerprint to change and then remain stable before it may be parsed.
        """
        if not self.page or self.page.is_closed():
            return False, ""

        deadline = asyncio.get_running_loop().time() + timeout_seconds
        stable_signature = ""
        stable_count = 0
        while asyncio.get_running_loop().time() < deadline:
            if self.get_current_conversation_id() != conversation_id:
                return False, ""

            ready = await self.page.evaluate("""() => {
                const chat = document.querySelector(
                    "div.chat section, section[class*='Fx($flx2)'], div[role='log'], main"
                );
                const input = document.querySelector(
                    "textarea[placeholder*='Nhập tin nhắn'], textarea[placeholder*='Type a message'], " +
                    "textarea[placeholder*='Nhắn tin'], div[contenteditable='true']"
                );
                return Boolean(chat && input);
            }""")
            signature = await self.get_chat_dom_signature() if ready else ""
            changed = not previous_signature or signature != previous_signature
            if ready and signature and changed:
                if signature == stable_signature:
                    stable_count += 1
                else:
                    stable_signature = signature
                    stable_count = 1
                if stable_count >= 2:
                    logger.info(f"Chat DOM ready for conversation {conversation_id}")
                    return True, signature
            else:
                stable_signature = ""
                stable_count = 0
            await asyncio.sleep(0.15)

        logger.warning(
            f"Chat DOM did not become safely associated with {conversation_id}; "
            "skipping this scan to avoid stale cross-conversation history."
        )
        return False, ""

    async def open_conversation(self, conversation_id_or_match_id: str) -> bool:
        """Navigate to a conversation and wait for its chat DOM to be ready."""
        if not self.page or self.page.is_closed():
            return False

        current_id = self.get_current_conversation_id()
        previous_signature = (
            await self.get_chat_dom_signature()
            if current_id != conversation_id_or_match_id
            else ""
        )
        target_url = f"https://tinder.com/app/messages/{conversation_id_or_match_id}"
        try:
            if current_id != conversation_id_or_match_id:
                logger.info(f"Navigating to conversation {conversation_id_or_match_id}...")
                await self.page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            ready, _ = await self.wait_for_conversation_ready(
                conversation_id_or_match_id,
                previous_signature=previous_signature,
            )
            return ready
        except Exception as e:
            logger.warning(f"Failed to navigate to conversation: {e}")
            return False
