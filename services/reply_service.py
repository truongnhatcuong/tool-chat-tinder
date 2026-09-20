"""Service managing AI suggestions and sent message states."""
from datetime import datetime, timezone
from database.db import get_db_session
from database.repository import AIReplyRepository


class ReplyService:
    @staticmethod
    async def record_reply(conversation_id: str, input_text: str, output_text: str, status: str = "GENERATED") -> int:
        async with get_db_session() as session:
            repo = AIReplyRepository(session)
            reply = await repo.create_reply(conversation_id, input_text, output_text, status)
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
