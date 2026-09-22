"""Conversation Manager orchestrating state isolation, queues, and debouncers."""
import asyncio
from typing import Callable, Coroutine, Any
from config.settings import get_settings
from conversations.queue import ConversationState
from conversations.debounce import DebounceAccumulator
from conversations.worker import ConversationWorker
from utils.logger import logger


class ConversationManager:
    """Orchestrates isolated conversation threads and concurrent workers."""

    def __init__(
        self,
        ai_handler: Callable[[ConversationState, list[dict[str, str]]], Coroutine[Any, Any, None]]
    ):
        self.ai_handler = ai_handler
        self.settings = get_settings()
        self._states: dict[str, ConversationState] = {}
        self._debouncers: dict[str, DebounceAccumulator] = {}
        self._workers: dict[str, ConversationWorker] = {}
        self._lock = asyncio.Lock()
        self._handler_semaphore = asyncio.Semaphore(
            max(1, self.settings.automation.max_parallel_conversations)
        )

    def get_state(self, conversation_id: str) -> ConversationState | None:
        return self._states.get(conversation_id)

    def list_active_states(self) -> list[ConversationState]:
        return list(self._states.values())

    async def get_or_create_state(
        self,
        conversation_id: str,
        match_id: str,
        match_name: str,
        mode: str = "OFF"
    ) -> ConversationState:
        async with self._lock:
            if conversation_id not in self._states:
                state = ConversationState(
                    conversation_id=conversation_id,
                    match_id=match_id,
                    match_name=match_name,
                    mode=mode
                )
                self._states[conversation_id] = state

                # Create a dedicated per-conversation worker. The shared wrapper
                # enforces the configured global parallel-conversation limit.
                worker = ConversationWorker(state, self._run_ai_handler)
                self._workers[conversation_id] = worker
                worker.start()

                # Create debounce accumulator
                debounce_sec = self.settings.automation.message_debounce_seconds
                debouncer = DebounceAccumulator(
                    conversation_id=conversation_id,
                    debounce_seconds=debounce_sec,
                    on_flush=lambda msgs, cid=conversation_id: self._on_debounce_flush(cid, msgs)
                )
                self._debouncers[conversation_id] = debouncer
            else:
                # Refresh persisted per-person settings and replace placeholder
                # names such as "Match" once the sidebar/database resolves them.
                state = self._states[conversation_id]
                state.mode = mode
                state.match_id = match_id
                if match_name and match_name != "Match":
                    state.match_name = match_name

            return self._states[conversation_id]

    async def receive_message(
        self,
        conversation_id: str,
        match_id: str,
        match_name: str,
        sender: str,
        content: str,
        message_hash: str | None = None,
        mode: str | None = None,
    ) -> None:
        """Receive incoming message and feed into this match's isolated pipeline."""
        existing_state = self.get_state(conversation_id)
        effective_mode = mode or (existing_state.mode if existing_state else "OFF")
        state = await self.get_or_create_state(
            conversation_id,
            match_id,
            match_name,
            mode=effective_mode,
        )
        state.append_message(role="incoming", sender=sender, content=content)

        # Feed to debounce accumulator
        debouncer = self._debouncers[conversation_id]
        await debouncer.add_message(content, message_hash, conversation_id)

    async def _run_ai_handler(
        self,
        state: ConversationState,
        bundled_messages: list[dict[str, str]],
    ) -> None:
        """Run one conversation pipeline under the configured global limit."""
        async with self._handler_semaphore:
            await self.ai_handler(state, bundled_messages)

    async def _on_debounce_flush(self, conversation_id: str, bundled_messages: list[dict[str, str]]) -> None:
        state = self._states.get(conversation_id)
        if state:
            logger.info(
                f"Queuing bundled messages for {conversation_id} ({len(bundled_messages)} msgs)"
            )
            # Runtime bundles contain hashes and an immutable conversation ID.
            # Reject rather than enqueue if any pending item escaped its owner.
            if bundled_messages and isinstance(bundled_messages[0], dict):
                wrong_ids = {
                    m.get("conversation_id") for m in bundled_messages
                    if m.get("conversation_id") != conversation_id
                }
                if wrong_ids:
                    logger.error(
                        f"QUEUE_CHAT_ID mismatch for {conversation_id}: {sorted(wrong_ids)}; bundle dropped"
                    )
                    return
                from services.message_service import MessageService
                hashes = [m["hash"] for m in bundled_messages]
                await MessageService.update_messages_status(hashes, "GENERATING")
            await state.queue.put(bundled_messages)

    def set_mode(self, conversation_id: str, mode: str) -> None:
        if conversation_id in self._states:
            self._states[conversation_id].mode = mode
            logger.info(f"Mode for {conversation_id} updated to {mode}")

    def stop_all(self) -> None:
        """Stop all workers and cancel tasks."""
        for worker in self._workers.values():
            worker.stop()
        self._workers.clear()
        self._debouncers.clear()
        self._states.clear()
        logger.info("All conversation workers stopped.")
