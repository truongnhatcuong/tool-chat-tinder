"""Pydantic schema, RapidFuzz duplicate check, quality rules and the regenerate loop."""
import json
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai.generator import ResponseGenerator
from ai.memory import ConversationMemory
from ai.quality import (
    QualityContext,
    build_guidance,
    check_reply,
    find_duplicate_replies,
    find_repeated_questions,
)
from ai.schemas import AIReply, parse_ai_reply
from conversations.queue import ConversationState
from database.models import Base


def reply(messages, **kw):
    return AIReply(messages=messages, **kw)


def js(messages, **kw):
    return json.dumps({"action": "REPLY", "messages": messages, **kw}, ensure_ascii=False)


# ----------------------------- Pydantic -----------------------------

def test_parse_valid_json_and_defaults():
    r, err = parse_ai_reply(js(["ừa b á"], reply_style="Tease"))
    assert err is None and r.messages == ["ừa b á"] and r.reply_style == "tease"


def test_parse_string_messages_fences_and_extra_keys():
    r, err = parse_ai_reply('```json\n{"messages": "z hả :))", "foo": 1}\n```')
    assert err is None and r.messages == ["z hả :))"]


def test_parse_wait_variants():
    assert parse_ai_reply("WAIT")[0].action == "WAIT"
    assert parse_ai_reply('{"action": "wait", "messages": []}')[0].action == "WAIT"


def test_empty_messages_become_wait_and_cap_at_two():
    assert parse_ai_reply('{"action":"REPLY","messages":["", "  "]}')[0].action == "WAIT"
    r, _ = parse_ai_reply(js(["a a a a", "b b b b", "c c c c"]))
    assert len(r.messages) == 2


def test_unknown_style_falls_back_and_bad_json_reports_error():
    assert parse_ai_reply(js(["x y z w"], reply_style="banana"))[0].reply_style == "react"
    for bad in ("hello there", "{not json", "[1,2]", ""):
        r, err = parse_ai_reply(bad)
        assert r is None and err


def test_question_key_falls_back_to_intent():
    r, _ = parse_ai_reply(js(["b ở ĐN lâu chưa?"], intent="living_duration"))
    assert r.question_key == "living_duration" and r.asks_question


# ----------------------------- RapidFuzz duplicates -----------------------------

def test_duplicate_detection_exact_and_fuzzy():
    past = ["chưa hả :)) tối ni b tính làm gì z?"]
    assert find_duplicate_replies(["chưa hả :)) tối ni b tính làm gì z?"], past)
    assert find_duplicate_replies(["chưa hả, tối ni b tính làm gì z"], past)
    assert not find_duplicate_replies(["mai tui đi bida với bạn á"], past)


def test_duplicate_inside_one_reply_and_short_reactions_ignored():
    assert find_duplicate_replies(["b hay đi cf không nè", "b hay đi cf không nè"], [])
    assert not find_duplicate_replies(["z á"], ["z á"])  # too short to fuzzy-block


# ----------------------------- repeated questions -----------------------------

def test_repeated_question_by_key_and_by_wording():
    ctx = QualityContext(asked_keys=["living_duration_da_nang"], asked_questions=["b vào ĐN lâu chưa?"])
    assert find_repeated_questions(reply(["b ở ĐN được bao lâu rồi?"], question_key="living_duration_da_nang"), ctx)
    assert find_repeated_questions(reply(["b vào ĐN lâu chưa z?"]), ctx)
    assert not find_repeated_questions(reply(["b hay đi cf k?"], question_key="coffee_habit"), ctx)


def test_asking_what_they_already_said_is_rejected():
    ctx = QualityContext(their_texts=["em quê Huế mà học với làm ở ĐN"])
    assert find_repeated_questions(reply(["b làm ở ĐN hả?"]), ctx)
    assert not find_repeated_questions(reply(["b vào ĐN lâu chưa?"]), ctx)


# ----------------------------- style rhythm -----------------------------

def test_two_question_turns_then_no_question():
    ctx = QualityContext(last_asked=[True, True], last_styles=["question", "question"])
    assert check_reply(reply(["b hay đi cf k?"], reply_style="question"), ctx)
    assert not check_reply(reply(["ghê nha, tui cũng hay đi cf á"], reply_style="share"), ctx)
    assert "KHÔNG HỎI" in build_guidance(ctx)


def test_compliment_cooldown_and_style_streak():
    ctx = QualityContext(last_styles=["compliment", "share"], last_asked=[False, False])
    assert check_reply(reply(["vibe b dễ thương thật á"], reply_style="compliment"), ctx)
    ctx2 = QualityContext(last_styles=["tease", "tease"], last_asked=[False, False])
    assert check_reply(reply(["nghe lầy dữ nha b"], reply_style="tease"), ctx2)
    assert not check_reply(reply(["nghe lầy dữ nha b"], reply_style="react"), ctx2)


def test_active_user_gets_expand_hint():
    ctx = QualityContext(last_asked=[False, False, False], their_active=True)
    assert "mở rộng" in build_guidance(ctx)


# ----------------------------- regenerate loop -----------------------------

class ScriptedLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def chat(self, messages, **kwargs):
        self.prompts.append(messages)
        return self.outputs.pop(0)


def _state(history=None):
    st = ConversationState("c1", "c1", "Lan", mode="AUTO")
    for role, text in history or []:
        st.append_message(role, "You" if role == "outgoing" else "Lan", text)
    return st


@pytest.mark.asyncio
async def test_bad_first_draft_is_regenerated_with_reason():
    llm = ScriptedLLM([
        js(["hihi, giống nhau ghê =)) b thích đi chơi không?"], reply_style="question"),
        js(["ừa b á :) rảnh b hay đi đâu z"], reply_style="question"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["tớ à"])
    assert out == ["ừa b á :) rảnh b hay đi đâu z"]
    assert meta["regenerations"] == 1
    feedback = llm.prompts[1][-1]["content"]
    assert "vi phạm" in feedback or "hihi" in feedback


@pytest.mark.asyncio
async def test_invalid_json_then_valid():
    llm = ScriptedLLM(["xin chào đây là tin", js(["ủa thiệt hả :))"], reply_style="react")])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["mình chưa"])
    assert out == ["ủa thiệt hả :))"] and meta["regenerations"] == 1


@pytest.mark.asyncio
async def test_duplicate_of_sent_message_is_regenerated():
    st = _state([("outgoing", "tối ni b tính làm gì z?")])
    llm = ScriptedLLM([
        js(["tối ni b tính làm gì z?"], reply_style="question"),
        js(["nghe cũng vui á, tui cũng hay lượn phố tối"], reply_style="share"),
    ])
    out, _, _, _ = await ResponseGenerator(llm).generate_response(st, ["chưa nè"])
    assert out == ["nghe cũng vui á, tui cũng hay lượn phố tối"]


@pytest.mark.asyncio
async def test_bad_drafts_never_sent_and_bank_fallback_replaces_silence():
    bad = js(["Chào em nha :D"], reply_style="react")
    llm = ScriptedLLM([bad, bad, bad, bad])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["hello"])
    assert out and "Chào em nha :D" not in out           # the bad draft is never sent
    assert meta["fallback"] == "bank" and meta["gave_up"] is False
    assert len(llm.prompts) == 4  # 1 attempt + 2 regenerations + 1 rescue


@pytest.mark.asyncio
async def test_wait_is_only_accepted_for_goodnight_or_busy():
    llm = ScriptedLLM(['{"action": "WAIT", "messages": []}'])
    out, _, _, _ = await ResponseGenerator(llm).generate_response(_state(), ["chúc b ngủ ngon nha"])
    assert out == [] and len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_wait_for_a_normal_message_is_not_silence():
    """Reported: draft failed the rhythm check, the retry said WAIT, and nothing was sent."""
    st = _state([
        ("outgoing", "b hay đi đâu á"),
        ("incoming", "đi cf á"),
        ("outgoing", "nay b đi học hả"),
        ("incoming", "ừ"),
    ])
    wait = '{"action": "WAIT", "messages": []}'
    llm = ScriptedLLM([js(["b thường nghe nhạc gì z"], reply_style="question"), wait, wait, wait])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(st, ["cuối tuần cũng bận"])
    assert out, "they are waiting; the bot must answer"
    assert meta["fallback"] == "bank" and meta["asks_question"] is False   # asked twice already -> reaction only
    assert "không được WAIT" in llm.prompts[2][-1]["content"]          # told off after the WAIT
    assert "trả action WAIT" not in llm.prompts[1][-1]["content"]      # the retry note no longer invites WAIT


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
async def test_record_sent_reply_persists_and_feeds_next_context(session_factory):
    mem = ConversationMemory(ScriptedLLM([]), session_factory)
    await mem.record_sent_reply(
        "A", reply_style="question", asked=True,
        question_key="living_duration", question_texts=["b vào ĐN lâu chưa?"],
    )
    await mem.record_sent_reply("A", reply_style="share", asked=False)
    await mem.record_sent_reply("B", reply_style="tease", asked=False)

    ctx = await mem.build_context("A", ["ừ"])
    assert ctx.last_reply_styles == ["question", "share"]
    assert ctx.last_reply_asked == [True, False]
    assert ctx.questions_asked == ["b vào ĐN lâu chưa?"]
    assert "living_duration" in ctx.asked_intents
    assert "b vào ĐN lâu chưa?" in ctx.render()

    other = await mem.build_context("B", [])
    assert other.questions_asked == [] and other.last_reply_styles == ["tease"]  # isolation


@pytest.mark.asyncio
async def test_persisted_history_blocks_repeat_question_in_generator(session_factory):
    mem = ConversationMemory(ScriptedLLM([]), session_factory)
    await mem.record_sent_reply(
        "c1", reply_style="question", asked=True,
        question_key="living_duration", question_texts=["b vào ĐN lâu chưa?"],
    )
    ctx = await mem.build_context("c1", ["mới vào thôi"])
    llm = ScriptedLLM([
        js(["b ở ĐN được bao lâu rồi?"], reply_style="question", question_key="living_duration"),
        js(["z hả, chắc còn lạ lắm ha :))"], reply_style="react"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["mới vào thôi"], memory=ctx)
    assert out == ["z hả, chắc còn lạ lắm ha :))"] and meta["regenerations"] == 1


# ----------------------------- questions without "?" -----------------------------

def test_style_rule_sees_question_without_mark():
    ctx = QualityContext(last_asked=[True, True], last_styles=["question", "question"])
    assert check_reply(reply(["b hay đi đâu á"], reply_style="react"), ctx)          # no "?" but asks
    assert check_reply(reply(["b thường nghe nhạc gì z"], reply_style="share"), ctx)
    assert not check_reply(reply(["nghe cũng chill á, tui cũng hay lượn phố tối"], reply_style="share"), ctx)


def test_stacked_questions_without_marks_are_rejected():
    from ai.output_guard import find_violations
    assert find_violations(["b làm gì", "ở đâu z"], ["ừ"])
    assert not find_violations(["ủa z đồng hương luôn :))", "b vào ĐN lâu chưa"], ["ừ"])


@pytest.mark.asyncio
async def test_history_without_question_marks_still_counts_as_asked():
    st = _state([
        ("outgoing", "b hay đi đâu á"),
        ("incoming", "đi cf á"),
        ("outgoing", "nay b đi học hả"),
        ("incoming", "ừ"),
    ])
    llm = ScriptedLLM([
        js(["b thường nghe nhạc gì z"], reply_style="question"),      # third question in a row
        js(["nghe cũng chill á, tui cũng hay lượn phố tối"], reply_style="share"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(st, ["cuối tuần cũng bận"])
    assert out == ["nghe cũng chill á, tui cũng hay lượn phố tối"]
    assert meta["regenerations"] == 1 and meta["asks_question"] is False
    assert "KHÔNG" in llm.prompts[1][-1]["content"]


@pytest.mark.asyncio
async def test_meta_marks_unmarked_question_for_persistence():
    llm = ScriptedLLM([js(["b thường nghe nhạc gì z"], reply_style="share")])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["nay rảnh nè"])
    assert out and meta["asks_question"] is True and meta["reply_style"] == "question"
    assert meta["question_texts"] == ["b thường nghe nhạc gì z"]


# ----------------------------- recombined / re-used content -----------------------------

from ai.quality import (  # noqa: E402
    find_recombined_replies,
    find_repeated_fact_reactions,
    normalize,
)

SENT = ["ủa b có con luôn á :))", "nghe cũng thú vị ghê"]


def test_glued_old_messages_are_rejected():
    """The reported bug: two old messages merged into one 'new' message slipped past per-message matching."""
    glued = ["Ủa b có con luôn á :)) nghe thú vị ghê"]
    assert find_duplicate_replies(glued, SENT) == []          # per-message RapidFuzz alone misses it
    assert find_recombined_replies(glued, SENT)               # the new check catches it


def test_recombination_ignores_case_punctuation_emoji_spacing_and_order():
    for variant in (
        ["ủa   B có con luôn á 😂 nghe thú vị ghê!!"],
        ["nghe thú vị ghê, ủa b có con luôn á"],
        ["ỦA B CÓ CON LUÔN Á", "nghe   thú vị ghê..."],
    ):
        assert find_recombined_replies(variant, SENT), variant


def test_normalize_handles_unicode_forms():
    import unicodedata
    composed = "ủa b có con"
    decomposed = unicodedata.normalize("NFD", composed)
    assert normalize(decomposed) == normalize(composed)
    assert normalize("Ủa  B, có con luôn á :))") == "ủa b có con luôn á"


def test_genuinely_new_replies_pass_recombination():
    for new in (["b có con mấy tuổi rồi z"], ["chắc bận rộn lắm ha"], ["tui thì chưa tính tới vụ đó :))"]):
        assert find_recombined_replies(new, SENT) == [], new


def test_partial_reuse_of_one_phrase_with_new_content_is_allowed():
    assert find_recombined_replies(["ủa b có con luôn á, chắc bận rộn lắm mà vẫn rảnh nt ha"], SENT) == []


def _dialogue():
    return [
        ("them", "tui có con rồi"),
        ("me", "ủa b có con luôn á :))"),
        ("me", "nghe cũng thú vị ghê"),
    ]


def test_second_reaction_to_same_fact_is_rejected():
    ctx = QualityContext(dialogue=_dialogue(), new_texts=["ừ đó"], their_texts=["tui có con rồi", "ừ đó"])
    assert find_repeated_fact_reactions(reply(["ủa b có con rồi hả, hay ghê"]), ctx)
    assert find_repeated_fact_reactions(reply(["b có con nghe cũng lạ nha"]), ctx)


def test_followup_question_or_new_fact_is_allowed():
    ctx = QualityContext(dialogue=_dialogue(), new_texts=["ừ đó"], their_texts=["tui có con rồi", "ừ đó"])
    assert find_repeated_fact_reactions(reply(["con b mấy tuổi rồi z"]), ctx) == []   # deepening question
    assert find_repeated_fact_reactions(reply(["chắc bận rộn lắm ha"]), ctx) == []
    # they mention the fact again -> reacting to it is fine
    ctx2 = QualityContext(dialogue=_dialogue(), new_texts=["con tui 2 tuổi rồi"])
    assert find_repeated_fact_reactions(reply(["con 2 tuổi là quậy lắm nha"]), ctx2) == []


def test_recent_sent_appears_in_guidance():
    assert "ủa b có con luôn á" in build_guidance(QualityContext(recent_sent=SENT))


@pytest.mark.asyncio
async def test_generator_regenerates_glued_reply():
    st = _state([
        ("incoming", "tui có con rồi"),
        ("outgoing", "ủa b có con luôn á :))"),
        ("outgoing", "nghe cũng thú vị ghê"),
        ("incoming", "ừ đó"),
    ])
    llm = ScriptedLLM([
        js(["Ủa b có con luôn á :)) nghe thú vị ghê"], reply_style="react"),
        js(["chắc bận rộn lắm ha"], reply_style="react"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(st, ["ừ đó"])
    assert out == ["chắc bận rộn lắm ha"] and meta["regenerations"] == 1
    assert "ghép lại" in llm.prompts[1][-1]["content"] or "tái sử dụng" in llm.prompts[1][-1]["content"]


@pytest.mark.asyncio
async def test_generator_regenerates_second_reaction_to_same_fact():
    st = _state([
        ("incoming", "tui có con rồi"),
        ("outgoing", "ủa b có con luôn á :))"),
        ("outgoing", "nghe cũng thú vị ghê"),
        ("incoming", "ừ đó"),
    ])
    llm = ScriptedLLM([
        js(["ủa b có con rồi hả, hay ghê"], reply_style="react"),
        js(["chắc bận rộn lắm ha"], reply_style="react"),
    ])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(st, ["ừ đó"])
    assert out == ["chắc bận rộn lắm ha"] and meta["regenerations"] == 1
    assert "lần hai" in llm.prompts[1][-1]["content"]


def test_verbatim_old_phrase_plus_new_text_still_blocked_as_repeat_reaction():
    ctx = QualityContext(dialogue=_dialogue(), recent_sent=SENT, new_texts=["ừ đó"], their_texts=["tui có con rồi", "ừ đó"])
    assert check_reply(reply(["ủa b có con luôn á, chắc bận rộn lắm mà vẫn rảnh nt ha"]), ctx)


# ----------------------------- never leave them hanging -----------------------------

from ai.fallback_replies import QUESTIONS, REACTIONS  # noqa: E402


def test_every_bank_line_passes_the_quality_check_on_a_fresh_conversation():
    ctx = QualityContext()
    for text in REACTIONS:
        assert check_reply(reply([text], reply_style="react"), ctx) == [], text
    for text, key in QUESTIONS:
        assert check_reply(reply([text], reply_style="question", question_key=key), ctx) == [], text


def _stuck_state():
    """The reported chat: our last messages are 'chắc phải từ từ thôi á', they answered 'vừa sức th'."""
    return _state([
        ("outgoing", "khó hả :)) z cũng có lúc vậy"),
        ("outgoing", "chắc phải từ từ thôi á"),
        ("outgoing", "chiều nay làm bài đc k"),
        ("incoming", "đề mở mà dễ th"),
        ("outgoing", "hâhhaa, vậy là dễ hả :))"),
        ("incoming", "vừa sức th"),
    ])


@pytest.mark.asyncio
async def test_repeated_duplicate_drafts_end_in_a_real_reply_not_silence():
    dup = js(["vậy chắc phải từ từ thôi á :))"], reply_style="react")
    llm = ScriptedLLM([dup, dup, dup, dup])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_stuck_state(), ["vừa sức th"])
    assert out, "must not stay silent while they are waiting"
    assert all("từ từ thôi" not in m for m in out)
    assert meta["fallback"] in ("rescue", "bank")


@pytest.mark.asyncio
async def test_rescue_prompt_lists_reasons_and_recent_messages_and_its_reply_is_used():
    dup = js(["vậy chắc phải từ từ thôi á :))"], reply_style="react")
    good = js(["vừa sức thì ổn á, nghe cũng yên tâm r"], reply_style="share")   # we already asked twice -> no question
    llm = ScriptedLLM([dup, dup, dup, good])
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_stuck_state(), ["vừa sức th"])
    assert out == ["vừa sức thì ổn á, nghe cũng yên tâm r"] and meta["fallback"] == "rescue"
    rescue_prompt = llm.prompts[3][-1]["content"]
    assert "LẦN CUỐI" in rescue_prompt and "từ từ thôi" in rescue_prompt and "quá giống" in rescue_prompt


@pytest.mark.asyncio
async def test_gave_up_only_when_model_and_bank_all_fail(monkeypatch):
    import ai.fallback_replies as fb
    monkeypatch.setattr(fb, "REACTIONS", [])
    monkeypatch.setattr(fb, "QUESTIONS", [])
    monkeypatch.setattr(fb, "load_question_bank", lambda *a, **k: [])
    dup = js(["vậy chắc phải từ từ thôi á :))"], reply_style="react")
    llm = ScriptedLLM([dup, dup, dup, dup])
    out, safe, _, meta = await ResponseGenerator(llm).generate_response(_stuck_state(), ["vừa sức th"])
    assert out == [] and safe is False and meta["gave_up"] is True


# ----------------------------- cau_hoi.md as the rescue source -----------------------------

from ai.fallback_replies import _ranked_questions, load_question_bank, pick_fallback  # noqa: E402


def test_question_bank_is_loaded_from_cau_hoi_md():
    bank = load_question_bank()
    texts = [t for t, _, _ in bank]
    assert len(bank) >= 50
    assert "rảnh b hay làm gì z?" in texts                       # straight from cau_hoi.md section 4
    assert not any("xinh" in t for t in texts)                    # compliment section is skipped
    assert all(is_q for is_q in (True,))                          # (sanity placeholder, real check below)
    from ai.question_detector import is_question
    assert all(is_question(t) for t in texts)


def test_every_cau_hoi_question_passes_the_quality_check():
    for text, key, section in load_question_bank():
        assert check_reply(reply([text], reply_style="question", question_key=key), QualityContext()) == [], (section, text)


def test_ranking_prefers_the_topic_being_talked_about():
    import random
    ctx = QualityContext(dialogue=[("them", "tui hay xem phim kinh dị lắm")], new_texts=["mê phim lắm á"])
    top = [t for t, _ in _ranked_questions(ctx, random.Random(1))[:5]]
    assert any("phim" in t for t in top), top


def test_pick_fallback_uses_cau_hoi_questions_and_respects_the_streak():
    bank_texts = {t for t, _, _ in load_question_bank()}
    seen_question = False
    for _ in range(20):
        picked = pick_fallback(QualityContext())
        assert picked is not None
        if any(m in bank_texts for m in picked.messages):
            seen_question = True
    assert seen_question                                          # questions come from cau_hoi.md

    streak = QualityContext(last_asked=[True, True], last_styles=["question", "question"])
    for _ in range(20):
        picked = pick_fallback(streak)
        assert picked is not None and not picked.asks_question    # asked twice: reactions only


@pytest.mark.asyncio
async def test_fallback_question_is_persisted_like_any_other_question():
    llm = ScriptedLLM(["x", "x", "x", "x"])                       # unparseable every time
    out, _, _, meta = await ResponseGenerator(llm).generate_response(_state(), ["nay rảnh nè"])
    assert out and meta["fallback"] == "bank"
    if meta["asks_question"]:
        assert meta["question_key"].startswith("cau_hoi:") and meta["question_texts"]
