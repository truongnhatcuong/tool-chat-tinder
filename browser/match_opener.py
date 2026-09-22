"""Match Opener engine: iterates over new matches, reads profile, and sends personalized flirty openers."""
import asyncio
import random
import re
from typing import Any
from playwright.async_api import Page
from services.opener_service import OpenerService
from services.message_service import MessageService
from services.reply_service import ReplyService
from config.settings import get_settings
from utils.logger import logger
from utils.helpers import compute_message_hash


class MatchOpenerEngine:
    """Discovers matches without existing messages, generates clever openers, and sends them."""

    def __init__(self, page: Page, opener_service: OpenerService | None = None):
        self.page = page
        self.opener_service = opener_service or OpenerService()
        self.settings = get_settings()
        self._is_running = False

    async def extract_match_list(self) -> list[dict[str, str]]:
        """Extract all match conversation links currently in the sidebar."""
        matches = []
        try:
            # Read links already present in both sidebar tab panels without
            # changing the user's selected Matches/Messages tab.
            links = self.page.locator("a[href*='/app/messages/']")
            count = await links.count()
            for i in range(count):
                link = links.nth(i)
                href = await link.get_attribute("href") or ""
                m = re.search(r"/app/messages/([a-zA-Z0-9_\-]+)", href)
                if not m:
                    continue
                conv_id = m.group(1)
                text = await link.inner_text()
                name = text.split("\n")[0].strip() if text else "Match"
                matches.append({"conversation_id": conv_id, "name": name})
        except Exception as e:
            logger.warning(f"Error reading match list: {e}")
        return matches

    async def read_current_chat_profile(self, default_name: str = "") -> dict[str, Any]:
        """Read match profile visible on the right panel of the chat window."""
        profile: dict[str, Any] = {
            "name": default_name,
            "age": None,
            "bio": "",
            "goal": "",
            "interests": [],
            "distance": ""
        }

        try:
            # 1. Name and Age from profile heading: e.g. "Chíp 20 tuổi" or "Chíp 20"
            h1_el = self.page.locator("h1[aria-label*='tuổi'], h1[class*='display-1-strong']")
            if await h1_el.count() > 0:
                h1_text = (await h1_el.first.inner_text()).strip()
                m = re.search(r"^(.+?)\s*(\d{2})$", h1_text)
                if m:
                    profile["name"] = m.group(1).strip()
                    profile["age"] = int(m.group(2))
                else:
                    profile["name"] = h1_text

            # 2. Relationship Goal / Đang tìm kiếm
            goal_el = self.page.locator("div:has-text('Đang tìm kiếm') span")
            if await goal_el.count() > 0:
                profile["goal"] = (await goal_el.first.inner_text()).strip()

            # 3. Bio / Giới thiệu bản thân
            bio_el = self.page.locator("div:has-text('Giới thiệu bản thân') + div, div[class*='body-1-regular']")
            if await bio_el.count() > 0:
                profile["bio"] = (await bio_el.first.inner_text()).strip()

            # 4. Distance / Cách xa
            dist_el = self.page.locator("div:has-text('Cách xa')")
            if await dist_el.count() > 0:
                profile["distance"] = (await dist_el.first.inner_text()).strip()

        except Exception as e:
            logger.debug(f"Profile extract notice: {e}")

        return profile

    async def has_existing_messages(self) -> bool:
        """
        Check if any real message bubbles exist in the chat container.
        Accurately excludes the match banner ('Bạn đã tương hợp với...' / 'You matched with...').
        """
        try:
            return await self.page.evaluate("""() => {
                const sec = document.querySelector("div.chat section, section[class*='Fx($flx2)']");
                if (!sec) return false;

                // 1. Check for known message bubble selectors
                const msgEls = sec.querySelectorAll(
                    "div[class*='msg-'], div[class*='message-'], [data-testid*='message'], div[class*='theirs'], div[class*='mine'], div[class*='bubble']"
                );
                if (msgEls.length > 0) return true;

                // 2. Check for child elements other than h2 and match banner
                const directChildren = Array.from(sec.children);
                const nonBannerElements = directChildren.filter(el => {
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'h2') return false;
                    const text = el.innerText || '';
                    if (!text.trim()) return false;
                    if (text.includes('tương hợp') || text.toLowerCase().includes('you matched')) return false;
                    return true;
                });

                return nonBannerElements.length > 0;
            }""")
        except Exception as e:
            logger.warning(f"Error checking existing messages: {e}")
            return False

    async def send_opener_to_current_chat(self, conversation_id: str, opener_text: str) -> bool:
        """Input opener into chat textarea and dispatch."""
        if self.settings.dry_run:
            logger.info(
                f"[DRY RUN OPENER] Would send to '{conversation_id}': \"{opener_text}\""
            )
            return True

        # Locate chat input
        inputs = self.page.locator(
            "textarea[placeholder*='Nhập tin nhắn'], textarea[placeholder*='Type a message'], textarea:not([aria-hidden='true'])"
        )
        if await inputs.count() == 0:
            logger.warning(f"Could not find chat input for {conversation_id}")
            return False

        chat_input = inputs.first
        await chat_input.click()
        await chat_input.fill(opener_text)
        await asyncio.sleep(0.5)

        # Click Send button or press Enter
        send_btn = self.page.locator("button[type='submit']:not([disabled]), button[aria-label*='Gửi']:not([disabled]), button[aria-label*='Send']:not([disabled])")
        if await send_btn.count() > 0:
            await send_btn.first.click()
        else:
            await chat_input.press("Enter")
        logger.info(f"Sent opener to {conversation_id}: \"{opener_text}\"")

        # Save to database
        try:
            msg_hash = compute_message_hash(conversation_id, "You", opener_text)
            await MessageService.save_message_if_new(
                conversation_id=conversation_id,
                match_id=conversation_id,
                sender="You",
                role="outgoing",
                content=opener_text,
                message_hash=msg_hash
            )
            await ReplyService.record_reply(
                conversation_id=conversation_id,
                input_text="[NEW MATCH OPENER]",
                output_text=opener_text,
                status="SENT"
            )
        except Exception as e:
            logger.warning(f"DB save opener notice: {e}")

        return True

    async def run_opener_on_single_match(self, item: dict[str, str]) -> bool:
        """
        Process a single match. Returns True if an opener was sent, False otherwise.
        """
        conv_id = item["conversation_id"]
        name = item["name"]

        # 1. Check mode
        from services.match_service import MatchService
        mode = await MatchService.get_mode(conv_id)
        if mode != "AUTO":
            logger.info(f"Match {name} is {mode}. Skipping opener (AUTO required).")
            return False

        # 2. Check local database to avoid unnecessary navigation
        recent_msgs = await MessageService.get_recent_messages(conv_id, limit=1)
        if recent_msgs:
            logger.info(f"Conversation with {name} already has messages in DB. Skipping opener.")
            return False

        # 3. Navigate to conversation
        url = f"https://tinder.com/app/messages/{conv_id}"
        logger.info(f"Opening chat with {name} ({conv_id[:8]}...)...")
        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2.0)

        # Dismiss any popup if blocking
        from browser.popup_handler import dismiss_blocking_popups
        await dismiss_blocking_popups(self.page)

        # 4. Check DOM for existing messages (in case DB was empty but chat isn't)
        if await self.has_existing_messages():
            logger.info(f"Conversation with {name} already has messages in DOM. Skipping opener.")
            return False

        # 5. Read profile details
        profile = await self.read_current_chat_profile(default_name=name)
        logger.info(
            f"Match profile: Name={profile['name']}, Age={profile['age']}, Bio='{profile['bio'][:30]}', Goal='{profile['goal']}'"
        )

        # 6. Generate flirty / subtle opener
        opener = await self.opener_service.generate_opener(profile)
        logger.info(f"Opener crafted for {name}: \"{opener}\"")

        # 7. Send opener
        sent = await self.send_opener_to_current_chat(conv_id, opener)
        
        if sent:
            # Natural delay between openers (4 - 8s)
            delay = random.uniform(4.0, 8.0)
            logger.info(f"Cooling down for {delay:.1f}s before next action...")
            await asyncio.sleep(delay)
            return True

        return False

    async def run_openers_on_all_new_matches(self, max_openers: int = 10) -> int:
        """
        Iterate through all matches in sidebar.
        If no chat history exists, craft a flirty tailored opener and send it.
        """
        self._is_running = True
        logger.info("================ STARTING AUTO-OPENER BATCH ================")
        
        matches = await self.extract_match_list()
        logger.info(f"Found {len(matches)} matches in sidebar list.")

        sent_count = 0
        for item in matches:
            if not self._is_running or sent_count >= max_openers:
                break

            try:
                sent = await self.run_opener_on_single_match(item)
                if sent:
                    sent_count += 1
            except Exception as e:
                logger.warning(f"Error processing opener for {item.get('name')}: {e}")

        logger.info(f"Completed auto-opener batch. Total openers sent: {sent_count}")
        self._is_running = False
        return sent_count

    def stop(self):
        self._is_running = False
        logger.info("Auto-opener stopped.")
