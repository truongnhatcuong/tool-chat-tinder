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
        message_hash: str,
        status: str = "NEW",
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
                message_hash=message_hash,
                status=status,
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

    @staticmethod
    async def update_messages_status(message_hashes: list[str], new_status: str) -> None:
        async with get_db_session() as session:
            repo = MessageRepository(session)
            await repo.update_messages_status(message_hashes, new_status)

    @staticmethod
    async def get_messages_by_status(conversation_id: str, status: str) -> list[MessageModel]:
        async with get_db_session() as session:
            repo = MessageRepository(session)
            return await repo.get_messages_by_status(conversation_id, status)

    @staticmethod
    async def get_statuses_by_hashes(message_hashes: list[str]) -> dict[str, str]:
        async with get_db_session() as session:
            repo = MessageRepository(session)
            return await repo.get_statuses_by_hashes(message_hashes)
