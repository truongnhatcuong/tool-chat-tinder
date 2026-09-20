"""Mock Tinder Service for unit and offline pipeline testing without touching real Tinder."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Coroutine, Any
from utils.helpers import compute_message_hash


@dataclass
class MockMessage:
    conversation_id: str
    match_id: str
    sender: str
    role: str
    content: str
    message_hash: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MockMatch:
    tinder_id: str
    name: str
    age: int
    bio: str
    interests: list[str]
    job: str = "Software Engineer"
    school: str = "Hanoi University"
    relationship_goal: str = "Long-term relationship"
    distance: str = "3 km away"


class MockTinderService:
    """Simulates Tinder events, new matches, and incoming messages."""

    def __init__(self):
        self.matches: dict[str, MockMatch] = {
            "match_001": MockMatch(
                tinder_id="match_001",
                name="Lan",
                age=24,
                bio="Thích cafe và du lịch, thích mèo và chụp ảnh :))",
                interests=["Coffee", "Travel", "Cats", "Photography"]
            ),
            "match_002": MockMatch(
                tinder_id="match_002",
                name="Mai",
                age=23,
                bio="Sinh viên năm cuối, mê âm nhạc acoustic.",
                interests=["Music", "Acoustic", "Books"]
            ),
            "match_003": MockMatch(
                tinder_id="match_003",
                name="Hương",
                age=25,
                bio="Designer tại HN. Thích đi dạo phố và chill.",
                interests=["Design", "Art", "Walking", "Chill"]
            ),
        }
        self.message_listeners: list[Callable[[MockMessage], Coroutine[Any, Any, None]]] = []

    def add_message_listener(self, listener: Callable[[MockMessage], Coroutine[Any, Any, None]]) -> None:
        self.message_listeners.append(listener)

    async def mock_message(
        self,
        match_id: str,
        name: str,
        message: str,
        conversation_id: str | None = None
    ) -> MockMessage:
        """Simulate an incoming message from a match."""
        conv_id = conversation_id or f"conv_{match_id}"
        msg_hash = compute_message_hash(conv_id, name, message)
        mock_msg = MockMessage(
            conversation_id=conv_id,
            match_id=match_id,
            sender=name,
            role="incoming",
            content=message,
            message_hash=msg_hash
        )
        for listener in self.message_listeners:
            asyncio.create_task(listener(mock_msg))
        return mock_msg

    async def simulate_rapid_fire(self, match_id: str, name: str, messages: list[str], delay_between: float = 0.5):
        """Send multiple messages rapidly to test debounce."""
        results = []
        for msg in messages:
            m = await self.mock_message(match_id=match_id, name=name, message=msg)
            results.append(m)
            await asyncio.sleep(delay_between)
        return results
