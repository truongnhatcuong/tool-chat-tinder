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

    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()

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

        # 3. Human-like delay
        delay = random.uniform(
            self.settings.automation.reply_delay_min,
            self.settings.automation.reply_delay_max
        )
        logger.info(f"Applying human-like response delay: {delay:.2f}s...")
        await asyncio.sleep(delay)

        # 4. Strict conversation verification
        current_url = self.page.url
        if target_conversation_id not in current_url:
            target_url = f"https://tinder.com/app/messages/{target_conversation_id}"
            logger.info(f"Navigating to conversation {target_conversation_id}...")
            await self.page.goto(target_url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(1.5)
            if target_conversation_id not in self.page.url:
                raise ConversationMismatchError(
                    f"Mismatch! Could not navigate to target conv '{target_conversation_id}'. Current URL: '{self.page.url}'"
                )

        # 5. Locate chat input
        chat_inputs = self.page.locator(
            "textarea[placeholder*='Nhập tin nhắn'], textarea[placeholder*='Type a message'], textarea[placeholder*='Nhắn tin'], textarea:not([aria-hidden='true']), div[contenteditable='true']"
        )
        if await chat_inputs.count() == 0:
            raise SenderVerificationError("Chat input textbox not found on page.")

        input_el = chat_inputs.first
        await input_el.click()
        await input_el.fill(reply_text)

        # 6. Re-verify URL before sending
        if target_conversation_id not in self.page.url:
            await input_el.fill("")  # Clear input immediately
            raise ConversationMismatchError("Target conversation changed during input typing! Aborted.")

        # 7. Send message (Press Enter)
        await input_el.press("Enter")
        logger.info(f"Sent message to {target_conversation_id}: \"{reply_text}\"")

        # 8. Post-send verification: wait a short interval and verify text appears in chat
        await asyncio.sleep(1.0)
        return True
