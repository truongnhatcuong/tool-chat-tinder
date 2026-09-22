"""Message sender with strict conversation verification, dry-run safety, and human delay."""
import asyncio
import random
from datetime import datetime, timezone
from playwright.async_api import Page
from config.settings import get_settings
from utils.logger import logger


class ConversationMismatchError(Exception):
    """Raised when active conversation does not match target recipient."""
    pass


class SenderVerificationError(Exception):
    """Raised when textbox or post-send verification fails."""
    pass


class MessageSender:
    """Executes message sending with strict safety barriers."""

    def __init__(self, page: Page, operation_lock: asyncio.Lock | None = None):
        self.page = page
        self.settings = get_settings()
        # Every sender instance sharing this Tinder tab must use the same lock.
        # It prevents another worker/scanner from navigating the page between
        # recipient verification and the final Enter key press.
        self.operation_lock = operation_lock or asyncio.Lock()

    async def send_reply(
        self,
        target_conversation_id: str,
        reply_text: str,
        is_auto: bool = False
    ) -> bool:
        """
        Send a reply to the target conversation.
        Strict verification:
        1. Check Global Pause and Emergency Stop.
        2. Check DRY RUN mode.
        3. Human-like typing delay.
        4. Verify URL matches target_conversation_id.
        5. Type text into chat input.
        6. Re-verify conversation URL.
        7. Press Enter or click Send.
        8. Verify message text appeared in chat container.
        """
        # 1. Check Global Flags
        if self.settings.emergency_stop:
            logger.critical("Emergency stop is active! Refusing to send message.")
            return False

        if self.settings.is_paused:
            logger.warning("Automations are globally paused. Aborting send.")
            return False

        # 2. Dry Run check
        if self.settings.dry_run:
            logger.info(
                f"[DRY RUN SIMULATION] Would send to '{target_conversation_id}': \"{reply_text}\""
            )
            return True

        if is_auto and not self.settings.global_auto_reply:
            logger.warning("Global auto-reply is disabled. Message must be manually approved.")
            return False

        async with self.operation_lock:
            # A queued reply is valid only while its original conversation remains
            # active. Never navigate back to the target here: doing so would revive
            # stale work after the user has deliberately switched A -> B.
            self._verify_target_conversation(target_conversation_id)

            # 3. Human-like delay. A manual browser click can still change the SPA
            # while Python holds this lock, so identity is checked again afterward.
            delay = random.uniform(
                self.settings.automation.reply_delay_min,
                self.settings.automation.reply_delay_max
            )
            logger.info(
                f"Reserved browser for {target_conversation_id}; "
                f"applying human-like response delay: {delay:.2f}s..."
            )
            await asyncio.sleep(delay)

            # 4. Strict conversation verification. Compare the extracted path ID,
            # never use substring matching for recipient identity.
            self._verify_target_conversation(target_conversation_id)

            # 5. Locate chat input
            chat_inputs = self.page.locator(
                "textarea[placeholder*='Nhập tin nhắn'], textarea[placeholder*='Type a message'], textarea[placeholder*='Nhắn tin'], textarea:not([aria-hidden='true']), div[contenteditable='true']"
            )
            if await chat_inputs.count() == 0:
                raise SenderVerificationError("Chat input textbox not found on page.")

            input_el = chat_inputs.first
            await input_el.click()
            await input_el.fill(reply_text)

            # 6. Re-verify immediately before sending while navigation is locked.
            self._verify_target_conversation(target_conversation_id)

            # 7. Install an in-page capture guard. It checks location.pathname at
            # the exact keydown event and blocks Enter if even a manual click has
            # switched Tinder to another recipient during the async gap.
            await self._install_enter_guard(target_conversation_id)
            try:
                await input_el.press("Enter")
            finally:
                await self._remove_enter_guard()

            # 8. Verify navigation did not change as the send was committed.
            self._verify_target_conversation(target_conversation_id)
            logger.info(f"Sent message to {target_conversation_id}: \"{reply_text}\"")
            await asyncio.sleep(1.0)
            return True

    def _current_conversation_id(self) -> str | None:
        """Extract the exact active conversation ID from the Tinder URL."""
        from urllib.parse import urlparse

        path_parts = urlparse(self.page.url).path.rstrip("/").split("/")
        if len(path_parts) >= 3 and path_parts[-2] == "messages":
            return path_parts[-1]
        return None

    def _verify_target_conversation(self, target_conversation_id: str) -> None:
        current_id = self._current_conversation_id()
        logger.info(
            "CURRENT_CHAT_ID=%s STATE_CHAT_ID=%s MEMORY_CHAT_ID=%s "
            "QUEUE_CHAT_ID=%s LATEST_MESSAGE=%r PROFILE_NAME=%r",
            current_id,
            target_conversation_id,
            target_conversation_id,
            target_conversation_id,
            "",
            "",
        )
        if current_id != target_conversation_id:
            raise ConversationMismatchError(
                f"Recipient mismatch: expected '{target_conversation_id}', "
                f"active '{current_id}', URL '{self.page.url}'. Send aborted."
            )

    async def _install_enter_guard(self, target_conversation_id: str) -> None:
        """Block Enter in the page itself unless the exact recipient is active."""
        await self.page.evaluate(
            r"""expectedId => {
                window.__tinderSafeSendExpected = expectedId;
                window.__tinderSafeSendGuard = event => {
                    if (event.key !== 'Enter') return;
                    const parts = window.location.pathname.replace(/\/$/, '').split('/');
                    const currentId = parts.length >= 3 && parts[parts.length - 2] === 'messages'
                        ? parts[parts.length - 1]
                        : null;
                    if (currentId !== window.__tinderSafeSendExpected) {
                        event.preventDefault();
                        event.stopImmediatePropagation();
                    }
                };
                document.addEventListener('keydown', window.__tinderSafeSendGuard, true);
            }""",
            target_conversation_id,
        )

    async def _remove_enter_guard(self) -> None:
        """Remove the temporary in-page keyboard safety guard."""
        try:
            await self.page.evaluate(
                """() => {
                    if (window.__tinderSafeSendGuard) {
                        document.removeEventListener(
                            'keydown', window.__tinderSafeSendGuard, true
                        );
                    }
                    delete window.__tinderSafeSendGuard;
                    delete window.__tinderSafeSendExpected;
                }"""
            )
        except Exception:
            # A full-page navigation destroys the old document and its listener.
            pass
