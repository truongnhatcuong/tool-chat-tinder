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
        ai_handler: Callable[[ConversationState, list[str]], Coroutine[Any, Any, None]]
    ):
        self.ai_handler = ai_handler
        self.settings = get_settings()
        self._states: dict[str, ConversationState] = {}
        self._debouncers: dict[str, DebounceAccumulator] = {}
        self._workers: dict[str, ConversationWorker] = {}
        self._lock = asyncio.Lock()

    def get_state(self, conversation_id: str) -> ConversationState | None:
        return self._states.get(conversation_id)

    def list_active_states(self) -> list[ConversationState]:
        return list(self._states.values())

    async def get_or_create_state(
        self,
        conversation_id: str,
        match_id: str,
        match_name: str,
        mode: str = "AUTO"
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

                # Create dedicated worker
                worker = ConversationWorker(state, self.ai_handler)
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

            return self._states[conversation_id]

    async def receive_message(
        self,
        conversation_id: str,
        match_id: str,
        match_name: str,
        sender: str,
        content: str
    ) -> None:
        """Receive incoming message and feed into this match's isolated pipeline."""
        state = await self.get_or_create_state(conversation_id, match_id, match_name)
        state.append_message(role="incoming", sender=sender, content=content)

        # Feed to debounce accumulator
        debouncer = self._debouncers[conversation_id]
        await debouncer.add_message(content)

    async def _on_debounce_flush(self, conversation_id: str, bundled_messages: list[str]) -> None:
        state = self._states.get(conversation_id)
        if state:
            logger.info(
                f"Queuing bundled messages for {conversation_id} ({len(bundled_messages)} msgs)"
            )
            await state.queue.put(bundled_messages)

    def set_mode(self, conversation_id: str, mode: str) -> None:
        if conversation_id in self._states:
            self._states[conversation_id].mode = mode
            logger.info(f"Mode for {conversation_id} updated to {mode}")

    def set_all_modes(self, mode: str) -> None:
        """Update mode for all active conversation states in memory."""
        for state in self._states.values():
            state.mode = mode
        logger.info(f"Updated memory mode for ALL active conversation states ({len(self._states)}) -> {mode}")

    def stop_all(self) -> None:
        """Stop all workers and cancel tasks."""
        for worker in self._workers.values():
            worker.stop()
        self._workers.clear()
        self._debouncers.clear()
        self._states.clear()
        logger.info("All conversation workers stopped.")
