"""Service managing AI suggestions and sent message states."""
from datetime import datetime, timezone
from database.db import get_db_session
from database.repository import AIReplyRepository


class ReplyService:
    @staticmethod
    async def record_reply(
        conversation_id: str,
        input_text: str,
        output_text: str,
        status: str = "GENERATED",
        message_hashes: str | None = None
    ) -> int:
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            reply = await repo.create_reply(conversation_id, input_text, output_text, status, message_hashes)
            return reply.id

    @staticmethod
    async def mark_sent(reply_id: int) -> None:
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            await repo.update_status(reply_id, status="SENT", sent_at=datetime.now(timezone.utc))

    @staticmethod
    async def mark_rejected(reply_id: int) -> None:
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            await repo.update_status(reply_id, status="REJECTED")

    @staticmethod
    async def update_status_raw(reply_id: int, status: str) -> None:
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            await repo.update_status(reply_id, status=status)

    @staticmethod
    async def get_latest_reply(conversation_id: str):
        from database.models import AIReplyModel
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            return await repo.get_latest_reply(conversation_id)
