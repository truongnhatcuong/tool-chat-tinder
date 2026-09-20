"""Tests verifying strict conversation isolation, queue ordering, and debouncing."""
import asyncio
import pytest
from conversations.manager import ConversationManager
from conversations.queue import ConversationState
from conversations.debounce import DebounceAccumulator


@pytest.mark.asyncio
async def test_debounce_accumulator_groups_rapid_messages():
    flushed_bundles = []

    async def on_flush(messages: list[str]):
        flushed_bundles.append(messages)

    debouncer = DebounceAccumulator(
        conversation_id="conv_test_debounce",
        debounce_seconds=0.2,  # fast interval for test
        on_flush=on_flush
    )

    # Send 3 rapid messages
    await debouncer.add_message("ê")
    await asyncio.sleep(0.05)
    await debouncer.add_message("anh đang làm gì đó")
    await asyncio.sleep(0.05)
    await debouncer.add_message(":))")

    # Before debounce expires, nothing should be flushed
    assert len(flushed_bundles) == 0

    # Wait for debounce to expire
    await asyncio.sleep(0.25)

    # Exactly 1 flush containing all 3 messages in order
    assert len(flushed_bundles) == 1
    assert flushed_bundles[0] == ["ê", "anh đang làm gì đó", ":))"]


@pytest.mark.asyncio
async def test_conversation_isolation_and_ordering():
    """
    Simulate:
    Lan sends 3 messages: [L1, L2, L3]
    Mai sends 5 messages: [M1, M2, M3, M4, M5]
    Hương sends 2 messages: [H1, H2]
    Tool must process them in parallel without mixing contexts and preserving order.
    """
    processed_calls: dict[str, list[str]] = {
        "conv_lan": [],
        "conv_mai": [],
        "conv_huong": []
    }

    async def mock_ai_handler(state: ConversationState, bundled_messages: list[str]):
        # Simulate slight processing latency
        await asyncio.sleep(0.02)
        processed_calls[state.conversation_id].extend(bundled_messages)

    manager = ConversationManager(ai_handler=mock_ai_handler)

    # Send messages concurrently across conversations
    async def send_lan():
        for i in range(1, 4):
            await manager.receive_message("conv_lan", "match_lan", "Lan", "Lan", f"L{i}")
            await asyncio.sleep(0.01)

    async def send_mai():
        for i in range(1, 6):
            await manager.receive_message("conv_mai", "match_mai", "Mai", "Mai", f"M{i}")
            await asyncio.sleep(0.01)

    async def send_huong():
        for i in range(1, 3):
            await manager.receive_message("conv_huong", "match_huong", "Hương", "Hương", f"H{i}")
            await asyncio.sleep(0.01)

    await asyncio.gather(send_lan(), send_mai(), send_huong())

    # Manually flush debouncers immediately for fast test completion
    for cid in ["conv_lan", "conv_mai", "conv_huong"]:
        debouncer = manager._debouncers.get(cid)
        if debouncer:
            await debouncer.flush_immediately()

    # Allow worker tasks to complete
    await asyncio.sleep(0.1)

    # Check that each conversation received strictly its own messages in exact order
    assert processed_calls["conv_lan"] == ["L1", "L2", "L3"]
    assert processed_calls["conv_mai"] == ["M1", "M2", "M3", "M4", "M5"]
    assert processed_calls["conv_huong"] == ["H1", "H2"]

    # Verify state isolation: history of Lan must NOT contain any message from Mai or Hương
    lan_state = manager.get_state("conv_lan")
    mai_state = manager.get_state("conv_mai")
    huong_state = manager.get_state("conv_huong")

    assert all(m["sender"] == "Lan" for m in lan_state.history)
    assert all(m["sender"] == "Mai" for m in mai_state.history)
    assert all(m["sender"] == "Hương" for m in huong_state.history)

    manager.stop_all()
