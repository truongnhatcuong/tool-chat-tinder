"""Debounce accumulator for grouping rapid consecutive messages from the same match."""
import asyncio
from typing import Callable, Coroutine, Any
from utils.logger import logger


class DebounceAccumulator:
    """Accumulates incoming messages and fires callback only after quiet period."""

    def __init__(
        self,
        conversation_id: str,
        debounce_seconds: float,
        on_flush: Callable[[list[dict[str, str]]], Coroutine[Any, Any, None]]
    ):
        self.conversation_id = conversation_id
        self.debounce_seconds = debounce_seconds
        self.on_flush = on_flush
        self._buffered_messages: list[dict[str, str]] = []
        self._timer_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def add_message(
        self,
        content: str,
        message_hash: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Add a message and reset or start debounce countdown."""
        async with self._lock:
            # Runtime messages carry their immutable conversation identity all
            # the way through debounce and queue. String-only values remain for
            # lightweight tests that do not use persistence.
            if message_hash is None:
                self._buffered_messages.append(content)
            else:
                self._buffered_messages.append({
                    "conversation_id": conversation_id or self.conversation_id,
                    "content": content,
                    "hash": message_hash,
                })
            
            # Cancel existing countdown timer to reset debounce period
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                logger.debug(f"Debounce timer reset for conversation {self.conversation_id}")

            self._timer_task = asyncio.create_task(self._wait_and_flush())

    async def _wait_and_flush(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
            async with self._lock:
                if not self._buffered_messages:
                    return
                messages_to_process = list(self._buffered_messages)
                self._buffered_messages.clear()
            
            logger.info(
                f"Debounce expired for {self.conversation_id}. Flushing {len(messages_to_process)} bundled messages."
            )
            await self.on_flush(messages_to_process)
        except asyncio.CancelledError:
            # Timer was reset by another incoming message
            pass
        except Exception as e:
            logger.error(f"Error in debounce callback for {self.conversation_id}: {e}")

    async def flush_immediately(self) -> None:
        """Force flush all buffered messages without waiting."""
        async with self._lock:
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
            if not self._buffered_messages:
                return
            msgs = list(self._buffered_messages)
            self._buffered_messages.clear()
        await self.on_flush(msgs)
