"""Service coordinating message storage, duplicate checks, and retrieval."""
from database.db import get_db_session
from database.repository import MessageRepository, ConversationRepository
from database.models import MessageModel
from utils.logger import logger


class MessageService:
    """Handles persistence and query operations for incoming/outgoing messages."""

    @staticmethod
    async def save_message_if_new(
        conversation_id: str,
        match_id: str,
        sender: str,
        role: str,
        content: str,
        message_hash: str
    ) -> MessageModel | None:
        async with get_db_session() as session:
            msg_repo = MessageRepository(session)
            conv_repo = ConversationRepository(session)

            # Ensure conversation record exists
            await conv_repo.upsert_conversation(
                conversation_id=conversation_id,
                match_id=match_id
            )

            # Insert message
            msg = await msg_repo.add_message(
                conversation_id=conversation_id,
                match_id=match_id,
                sender=sender,
                role=role,
                content=content,
                message_hash=message_hash
            )
            return msg

    @staticmethod
    async def get_recent_messages(conversation_id: str, limit: int = 20) -> list[dict]:
        async with get_db_session() as session:
            repo = MessageRepository(session)
            models = await repo.get_recent_messages(conversation_id, limit=limit)
            return [
                {
                    "sender": m.sender,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat()
                }
                for m in models
            ]
