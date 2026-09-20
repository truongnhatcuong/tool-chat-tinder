"""Unit tests for database repositories and duplicate hash prevention."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.models import Base
from database.repository import (
    MatchRepository,
    ConversationRepository,
    MessageRepository,
    AIReplyRepository
)
from utils.helpers import compute_message_hash


@pytest_asyncio.fixture
async def async_session():
    # Use in-memory SQLite for high-speed test isolation
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_upsert_and_retrieve(async_session: AsyncSession):
    repo = MatchRepository(async_session)
    match = await repo.upsert_match(
        tinder_id="match_test_01",
        name="Lan",
        age=24,
        bio="Cafe lover",
        mode="SUGGEST"
    )
    await async_session.commit()
    assert match.id is not None
    assert match.name == "Lan"

    # Update mode
    await repo.update_mode("match_test_01", "AUTO")
    await async_session.commit()

    retrieved = await repo.get_by_tinder_id("match_test_01")
    assert retrieved is not None
    assert retrieved.mode == "AUTO"


@pytest.mark.asyncio
async def test_batch_mode_update(async_session: AsyncSession):
    repo = MatchRepository(async_session)
    await repo.upsert_match(tinder_id="match_01", name="Alice", mode="AUTO")
    await repo.upsert_match(tinder_id="match_02", name="Bob", mode="SUGGEST")
    await async_session.commit()

    # Batch update to OFF
    updated_count = await repo.update_all_modes("OFF")
    await async_session.commit()
    assert updated_count == 2

    m1 = await repo.get_by_tinder_id("match_01")
    m2 = await repo.get_by_tinder_id("match_02")
    assert m1.mode == "OFF"
    assert m2.mode == "OFF"


@pytest.mark.asyncio
async def test_delete_match_on_unmatch(async_session: AsyncSession):
    repo = MatchRepository(async_session)
    await repo.upsert_match(tinder_id="match_to_delete", name="Chloe", mode="AUTO")
    await async_session.commit()

    # Verify exists
    assert await repo.get_by_tinder_id("match_to_delete") is not None

    # Delete on unmatch
    deleted = await repo.delete_by_tinder_id("match_to_delete")
    await async_session.commit()
    assert deleted is True

    # Verify deleted
    assert await repo.get_by_tinder_id("match_to_delete") is None


@pytest.mark.asyncio
async def test_message_duplicate_hash_rejection(async_session: AsyncSession):
    repo = MessageRepository(async_session)
    conv_id = "conv_lan_01"
    sender = "Lan"
    content = "Hello there!"
    msg_hash = compute_message_hash(conv_id, sender, content)

    # First insertion succeeds
    first_msg = await repo.add_message(
        conversation_id=conv_id,
        match_id="match_test_01",
        sender=sender,
        role="incoming",
        content=content,
        message_hash=msg_hash
    )
    await async_session.commit()
    assert first_msg is not None

    # Second insertion with the same hash MUST return None (idempotent / deduplicated)
    duplicate_msg = await repo.add_message(
        conversation_id=conv_id,
        match_id="match_test_01",
        sender=sender,
        role="incoming",
        content=content,
        message_hash=msg_hash
    )
    assert duplicate_msg is None

    # Verify count is strictly 1
    count = await repo.count_by_conversation(conv_id)
    assert count == 1


@pytest.mark.asyncio
async def test_ai_reply_workflow(async_session: AsyncSession):
    repo = AIReplyRepository(async_session)
    conv_id = "conv_test_02"
    
    reply = await repo.create_reply(
        conversation_id=conv_id,
        input_text="Hi!",
        output_text="Hello! Nice to meet you :))",
        status="GENERATED"
    )
    await async_session.commit()
    assert reply.id is not None
    assert reply.status == "GENERATED"

    # Update status to APPROVED
    await repo.update_status(reply.id, "APPROVED")
    await async_session.commit()

    latest = await repo.get_latest_reply(conv_id)
    assert latest is not None
    assert latest.status == "APPROVED"
