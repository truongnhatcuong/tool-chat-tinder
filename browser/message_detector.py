"""Message detector extracting incoming and outgoing messages from current chat view."""
import asyncio
from typing import Callable, Coroutine, Any
from playwright.async_api import Page
from utils.helpers import compute_message_hash
from utils.logger import logger


class MessageDetector:
    """Monitors the active conversation message view and detects newly arrived messages."""

    def __init__(self, page: Page):
        self.page = page
        self._is_running = False

    async def scroll_to_top_of_history(self, max_scrolls: int = 25) -> None:
        """
        Scroll the chat container all the way up so Tinder renders older messages
        that are not visible by default. Without this, MessageDetector only ever
        sees whatever is currently on screen, and any history predating the tool's
        first visit to this conversation would be silently missing from the DB
        (and therefore invisible to the AI memory context).
        Safe to call repeatedly: stops early once scrollTop stops decreasing.
        """
        if not self.page or self.page.is_closed():
            return
        try:
            for _ in range(max_scrolls):
                reached_top = await self.page.evaluate("""() => {
                    const sec = document.querySelector("div.chat section, section[class*='Fx($flx2)'], div[role='log']");
                    const container = sec ? sec.closest('[class*=\"Ov(a)\"], [style*=\"overflow\"]') || sec.parentElement : null;
                    const scrollable = container || document.querySelector("main");
                    if (!scrollable) return true;
                    const before = scrollable.scrollTop;
                    scrollable.scrollTop = 0;
                    return before <= 0;
                }""")
                if reached_top:
                    break
                await asyncio.sleep(0.35)
        except Exception as e:
            logger.debug(f"Scroll-to-top history backfill notice: {e}")

    async def detect_messages_in_current_chat(
        self,
        conversation_id: str,
        match_id: str,
        match_name: str
    ) -> list[dict[str, Any]]:
        """Extract all visible messages from the chat container."""
        if not self.page or self.page.is_closed():
            return []

        detected = []
        try:
            raw_messages = await self.page.evaluate("""() => {
                const sec = document.querySelector("div.chat section, section[class*='Fx($flx2)'], div[role='log']");
                const container = sec || document.querySelector("main");
                if (!container) return [];

                // 1. Find all candidate message bubble elements.
                // Prefer block-level bubble containers over generic text spans to avoid
                // the same message being matched twice (wrapper + inner text node) with
                // conflicting role guesses.
                const blockCandidates = Array.from(container.querySelectorAll(
                    "div[class*='msg-'], div[class*='message-'], [data-testid*='message'], div[class*='theirs'], div[class*='mine'], div[class*='bubble']"
                ));
                const spanFallback = Array.from(container.querySelectorAll("span[class*='text']"));
                // Only use the generic span selector for leaf nodes not already covered
                // by a block-level candidate (its own ancestor or descendant).
                const candidates = blockCandidates.concat(
                    spanFallback.filter(span => !blockCandidates.some(
                        block => block === span || block.contains(span) || span.contains(block)
                    ))
                );

                const list = [];
                const seenTexts = new Set();
                const usedElements = [];

                for (const el of candidates) {
                    const rawText = (el.innerText || '').trim();
                    if (!rawText) continue;
                    // Ignore banners, headers, timestamps
                    if (rawText.includes('tương hợp') || rawText.toLowerCase().includes('you matched')) continue;
                    if (el.closest('h1') || el.closest('h2') || el.closest('h3')) continue;

                    // Skip if this element is nested inside (or wraps) an element we
                    // already processed, to avoid double-counting the same bubble.
                    if (usedElements.some(used => used === el || used.contains(el) || el.contains(used))) {
                        continue;
                    }

                    // Determine role: prefer the explicit accessible label Tinder renders
                    // for each bubble ("Bạn: ..." / "You: ..." for our own messages),
                    // since it is the most reliable signal and never mislabels ownership.
                    const cls = (el.className || '') + ' ' + (el.parentElement ? el.parentElement.className : '');
                    const style = window.getComputedStyle(el);
                    const parentStyle = el.parentElement ? window.getComputedStyle(el.parentElement) : null;
                    const rect = el.getBoundingClientRect();
                    const containerRect = container.getBoundingClientRect();

                    let isOutgoing = false;
                    let roleDetermined = false;
                    let text = rawText;
                    if (/^(Bạn|You)\\s*:/i.test(rawText)) {
                        isOutgoing = true;
                        roleDetermined = true;
                        text = rawText.replace(/^(Bạn|You)\\s*:\\s*/i, '').trim();
                        if (!text) continue;
                    } else {
                        // Screen-reader label "<Name>:\\n<message>" on their bubbles
                        const lm = rawText.match(/^[^\\n:]{1,40}:\\s*\\n([\\s\\S]+)$/);
                        if (lm) {
                            text = lm[1].trim();
                            isOutgoing = false;
                            roleDetermined = true;
                        }
                    }

                    if (!roleDetermined) {
                        const ownMarkers = ['mine', 'outgoing', 'self', 'sent', 'ta(end)', 'gradient'];
                        const theirMarkers = ['theirs', 'incoming', 'their', 'received'];
                        const clsLower = cls.toLowerCase();
                        if (ownMarkers.some(m => clsLower.includes(m))) {
                            isOutgoing = true;
                            roleDetermined = true;
                        } else if (theirMarkers.some(m => clsLower.includes(m))) {
                            isOutgoing = false;
                            roleDetermined = true;
                        }
                    }

                    if (!roleDetermined && parentStyle) {
                        // Modern flex-based chat rows often align our own bubbles to the
                        // end of the row via flex-end/justify-content.
                        const justify = (parentStyle.justifyContent || '').toLowerCase();
                        const alignSelf = (style.alignSelf || '').toLowerCase();
                        if (justify.includes('end') || alignSelf.includes('end')) {
                            isOutgoing = true;
                            roleDetermined = true;
                        } else if (justify.includes('start') || alignSelf.includes('start')) {
                            isOutgoing = false;
                            roleDetermined = true;
                        }
                    }

                    if (!roleDetermined) {
                        const distRight = containerRect.right - rect.right;
                        const distLeft = rect.left - containerRect.left;
                        isOutgoing = distLeft > distRight + 20;
                    }

                    usedElements.push(el);
                    const key = (isOutgoing ? 'out:' : 'in:') + text;
                    if (!seenTexts.has(key)) {
                        seenTexts.add(key);
                        list.push({
                            content: text,
                            role: isOutgoing ? 'outgoing' : 'incoming'
                        });
                    }
                }
                return list;
            }""")

            for item in raw_messages:
                role = item.get("role", "incoming")
                content = item.get("content", "").strip()
                if not content:
                    continue
                sender = "You" if role == "outgoing" else match_name
                msg_hash = compute_message_hash(conversation_id, sender, content)
                detected.append({
                    "conversation_id": conversation_id,
                    "match_id": match_id,
                    "sender": sender,
                    "role": role,
                    "content": content,
                    "message_hash": msg_hash
                })
        except Exception as e:
            logger.warning(f"Error reading chat messages: {e}")

        return detected
