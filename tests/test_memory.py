"""Tests for per-conversation memory (isolation, summarization watermark, analysis)."""
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai.memory import (
    ConversationMemory,
    analyze_address,
    detect_stage,
    extract_asked_questions,
)
from database.models import Base
from database.repository import MessageRepository
from utils.helpers import compute_message_hash


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return self.reply


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def factory():
        async with maker() as session:
            yield session
            await session.commit()

    yield factory
    await engine.dispose()


async def _add(factory, conv, role, text):
    async with factory() as s:
        await MessageRepository(s).add_message(
            conv, conv, "You" if role == "outgoing" else "Lan", role, text,
            compute_message_hash(conv, role, text + str(id(text))),
        )


@pytest.mark.asyncio
async def test_isolation_between_users(session_factory):
    await _add(session_factory, "A", "incoming", "tui học kinh tế")
    await _add(session_factory, "B", "incoming", "mình làm designer")
    mem = ConversationMemory(FakeLLM("{}"), session_factory)
    ctx = await mem.build_context("A", [])
    text = ctx.render()
    assert "kinh tế" in text and "designer" not in text


@pytest.mark.asyncio
async def test_pending_messages_not_duplicated(session_factory):
    await _add(session_factory, "A", "outgoing", "hello b :))")
    await _add(session_factory, "A", "incoming", "chào nha")
    mem = ConversationMemory(FakeLLM("{}"), session_factory)
    ctx = await mem.build_context("A", ["chào nha"])
    assert [m["content"] for m in ctx.recent] == ["hello b :))"]
    assert ctx.new_messages == ["chào nha"]


@pytest.mark.asyncio
async def test_old_messages_summarized_once_and_saved(session_factory):
    for i in range(60):
        await _add(session_factory, "A", "incoming" if i % 2 else "outgoing", f"tin so {i}")
    llm = FakeLLM('{"summary": "hai người mới quen", "facts": ["[họ] học kinh tế", "[họ] học kinh tế"]}')
    mem = ConversationMemory(llm, session_factory)

    ctx = await mem.build_context("A", [])
    assert llm.calls == 1
    assert ctx.summary == "hai người mới quen"
    assert ctx.facts == ["[họ] học kinh tế"]          # deduped
    assert len(ctx.recent) == 40

    # second call: watermark saved -> no new LLM call, memory loaded from DB
    ctx2 = await mem.build_context("A", [])
    assert llm.calls == 1
    assert ctx2.summary == "hai người mới quen"


@pytest.mark.asyncio
async def test_summarize_failure_keeps_data(session_factory):
    for i in range(60):
        await _add(session_factory, "A", "incoming", f"tin so {i}")
    mem = ConversationMemory(FakeLLM("not json"), session_factory)
    ctx = await mem.build_context("A", [])
    assert ctx.summary == "" and ctx.facts == []


def test_helpers():
    assert detect_stage(0) == "NEW_MATCH" and detect_stage(30) == "DEEP_CHAT"
    assert "tui" in analyze_address(["tui 2k4 nha", "tui đi ngủ"], ["mình ở đà nẵng"])
    assert extract_asked_questions(["hello b", "b sn bao nhiu z", "b hay đi đâu?"]) == [
        "b sn bao nhiu z", "b hay đi đâu?",
    ]
