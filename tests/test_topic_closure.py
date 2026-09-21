"""Closed topics: "hong á", "thôi bỏ qua", "đâu có"... end the topic and the newest message wins."""
import json
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai.generator import ResponseGenerator
from ai.memory import CLOSED_TOPIC_TTL, ConversationMemory
from ai.quality import QualityContext, build_closed_topic, build_guidance, check_reply, find_closed_topic_problems
from ai.schemas import AIReply
from ai.topic_closure import detect_closure
from conversations.queue import ConversationState
from database.models import Base

CLOSING = [
    "hong á", "không", "thôi bỏ qua", "k có gì", "đâu có", "Hông á :))", "thôi", "khum nha",
    "không có gì đâu", "thôi kệ đi", "đừng hỏi nữa", "k", "ko có đâu", "không phải đâu",
]
NOT_CLOSING = [
    "không biết", "không học kinh tế mà học luật", "chưa", "có", "em học năm 3", "hong biết á",
    "tui đi làm rồi", "ừ", "hông muốn đi đâu chơi hết á nha", "không thích cf lắm", "thôi được rồi tui kể",
]


@pytest.mark.parametrize("text", CLOSING)
def test_detects_closing_messages(text):
    assert detect_closure([text]), text


@pytest.mark.parametrize("text", NOT_CLOSING)
def test_longer_or_informative_messages_are_not_closures(text):
    assert detect_closure([text]) is None, text


def test_only_the_newest_message_of_the_bundle_counts():
    assert detect_closure(["em học năm 3", "hong á"])
    assert detect_closure(["hong á", "mà tui thích bida"]) is None


def reply(messages, **kw):
    return AIReply(messages=messages, **kw)


def _ctx_after_denial():
    dialogue = [("them", "em đang học"), ("me", "b có đi học không?")]
    closure = detect_closure(["hong á"])
    entry = build_closed_topic(closure, dialogue, ["hong á"])
    return QualityContext(
        dialogue=dialogue, new_texts=["hong á"], their_texts=["em đang học", "hong á"],
        closed_topics=[entry], closure_now=closure.phrase, closed_now=entry,
    )


def test_closed_topic_entry_comes_from_our_last_message():
    ctx = _ctx_after_denial()
    assert "học" in ctx.closed_now["tokens"] and ctx.closed_now["phrase"] == "hong á"


def test_reasking_explaining_or_reacting_to_closed_topic_is_rejected():
    ctx = _ctx_after_denial()
    for bad in (["b học ngành gì z"], ["ủa sao hong đi học z"], ["đi học vui mà, b thử coi"]):
        assert check_reply(reply(bad), ctx), bad


def test_soft_reaction_teasing_or_new_topic_is_allowed():
    ctx = _ctx_after_denial()
    for ok in (["ok hiểu r :))"], ["z cũng dc á"], ["vậy cuối tuần b hay lượn phố hả"]):
        assert find_closed_topic_problems(reply(ok), ctx) == [], ok


def test_they_reopening_the_topic_is_allowed():
    dialogue = [("me", "b có đi học không?")]
    closure = detect_closure(["hong á"])
    entry = build_closed_topic(closure, dialogue, ["hong á"])
    ctx = QualityContext(dialogue=dialogue, new_texts=["đi học chán lắm"], closed_topics=[entry])  # no closure now
    assert find_closed_topic_problems(reply(["đi học chán thiệt á"]), ctx) == []


def test_must_answer_newest_message_not_an_older_one():
    dialogue = [("them", "tui thích bida"), ("me", "b chơi giỏi ha")]
    closure = detect_closure(["đâu có"])
    entry = build_closed_topic(closure, dialogue, ["đâu có"])
    ctx = QualityContext(dialogue=dialogue, new_texts=["đâu có"], closed_topics=[entry], closure_now=closure.phrase)
    problems = find_closed_topic_problems(reply(["bida vui mà, tui cũng hay đi"]), ctx)
    assert any("tin cũ" in p or "đã bị họ đóng" in p for p in problems)
    assert find_closed_topic_problems(reply(["ok hiểu r =))"]), ctx) == []


def test_guidance_mentions_closure_and_newest_message():
    g = build_guidance(_ctx_after_denial())
    assert "CHỦ ĐỀ ĐÃ ĐÓNG" in g and "hong á" in g and "tin mới nhất" in g


# ----------------------------- generator flow -----------------------------

class ScriptedLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def chat(self, messages, **kwargs):
        self.prompts.append(messages)
        return self.outputs.pop(0)


def js(messages, **kw):
    return json.dumps({"action": "REPLY", "messages": messages, **kw}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_generator_rejects_reasking_after_denial_and_reports_closed_topic():
    st = ConversationState("c1", "c1", "Lan", mode="AUTO")
    st.append_message("incoming", "Lan", "em đang học")
    st.append_message("outgoing", "You", "b có đi học không?")
    llm = ScriptedLLM([
        js(["ủa sao hong đi học z, học vui mà"], reply_style="react"),
        js(["ok hiểu r :))"], reply_style="react"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(st, ["hong á"])
    assert out == ["ok hiểu r :))"] and meta["regenerations"] == 1
    assert "CHỦ ĐỀ ĐÃ ĐÓNG" in llm.prompts[0][-1]["content"]
    assert "đã bị họ đóng" in llm.prompts[1][-1]["content"]
    assert meta["closed_topic"] and "học" in meta["closed_topic"]["tokens"]


# ----------------------------- persistence -----------------------------

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


@pytest.mark.asyncio
async def test_closed_topic_persists_then_expires(session_factory):
    mem = ConversationMemory(ScriptedLLM([]), session_factory)
    entry = {"tokens": ["học"], "phrase": "hong á", "text": "b có đi học không?"}
    await mem.record_closed_topic("A", entry)
    await mem.record_closed_topic("A", entry)          # same turn twice -> stored once
    ctx = await mem.build_context("A", [])
    assert len(ctx.closed_topics) == 1 and ctx.closed_topics[0]["tokens"] == ["học"]

    for _ in range(CLOSED_TOPIC_TTL + 1):
        await mem.record_sent_reply("A", reply_style="react", asked=False)
    assert (await mem.build_context("A", [])).closed_topics == []          # expired

    other = await mem.build_context("B", [])
    assert other.closed_topics == []                                        # isolation
