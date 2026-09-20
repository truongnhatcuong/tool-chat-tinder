"""Conversation worker processing messages sequentially per match."""
import asyncio
from typing import Callable, Coroutine, Any
from conversations.queue import ConversationState
from utils.logger import logger


class ConversationWorker:
    """Processes messages for a single conversation in strict sequence."""

    def __init__(
        self,
        state: ConversationState,
        handler: Callable[[ConversationState, list[str]], Coroutine[Any, Any, None]]
    ):
        self.state = state
        self.handler = handler
        self._is_running = False
        self._task: asyncio.Task | None = None

    def start(self):
        if not self._is_running:
            self._is_running = True
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        logger.info(f"Worker started for conversation {self.state.conversation_id} ({self.state.match_name})")
        while self._is_running:
            try:
                # Wait for next bundle of messages from queue
                bundled_messages = await self.state.queue.get()
                if bundled_messages is None:  # Sentinel to stop
                    break

                # Process under this conversation's dedicated lock
                async with self.state.lock:
                    await self.handler(self.state, bundled_messages)

                self.state.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Isolated error handling: never crashes other conversation workers
                logger.exception(
                    f"Error in conversation worker {self.state.conversation_id}: {e}"
                )

    def stop(self):
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.debug(f"Worker stopped for {self.state.conversation_id}")
