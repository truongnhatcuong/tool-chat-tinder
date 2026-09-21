"""Per-conversation state and queue isolation structures."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ConversationState:
    """Isolated, independent state for an individual match."""
    conversation_id: str
    match_id: str
    match_name: str
    mode: str = "OFF"  # OFF, SUGGEST, AUTO
    status: str = "ACTIVE_CHAT"
    profile: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    pending_bundle: list[str] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def append_message(self, role: str, sender: str, content: str):
        """Append message strictly to this conversation's private history."""
        self.history.append({
            "role": role,
            "sender": sender,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        # Keep recent memory bounded (e.g. last 30 messages)
        if len(self.history) > 30:
            self.history = self.history[-30:]
