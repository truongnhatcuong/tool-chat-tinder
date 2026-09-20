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

                // 1. Find all candidate message bubble elements
                const candidates = container.querySelectorAll(
                    "div[class*='msg-'], div[class*='message-'], [data-testid*='message'], div[class*='theirs'], div[class*='mine'], div[class*='bubble'], span[class*='text']"
                );

                const list = [];
                const seenTexts = new Set();

                for (const el of candidates) {
                    const rawText = (el.innerText || '').trim();
                    if (!rawText) continue;
                    // Ignore banners, headers, timestamps
                    if (rawText.includes('tương hợp') || rawText.toLowerCase().includes('you matched')) continue;
                    if (el.closest('h1') || el.closest('h2') || el.closest('h3')) continue;

                    // Determine role: outgoing if contains 'mine', 'outgoing', or aligned right
                    const cls = (el.className || '') + ' ' + (el.parentElement ? el.parentElement.className : '');
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const containerRect = container.getBoundingClientRect();

                    let isOutgoing = false;
                    let text = rawText;
                    if (/^(Bạn|You)\\s*:/i.test(rawText)) {
                        isOutgoing = true;
                        text = rawText.replace(/^(Bạn|You)\\s*:\\s*/i, '').trim();
                        if (!text) continue;
                    }
                    if (isOutgoing) {
                        // already known as ours
                    } else if (cls.includes('mine') || cls.includes('outgoing') || cls.includes('Ta(end)') || cls.includes('gradient')) {
                        isOutgoing = true;
                    } else if (rect.left > containerRect.left + (containerRect.width * 0.45)) {
                        // Right half of container
                        isOutgoing = true;
                    }

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
