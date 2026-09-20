"""Database repository handling all CRUD queries asynchronously."""
import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import (
    MatchModel,
    ConversationModel,
    MessageModel,
    MatchProfileModel,
    AIReplyModel
)
from utils.logger import logger


class MatchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_tinder_id(self, tinder_id: str) -> MatchModel | None:
        stmt = select(MatchModel).where(MatchModel.tinder_id == tinder_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert_match(
        self,
        tinder_id: str,
        name: str,
        age: int | None = None,
        bio: str | None = None,
        profile_json: str | dict | None = None,
        mode: str | None = None
    ) -> MatchModel:
        if isinstance(profile_json, dict):
            profile_json = json.dumps(profile_json, ensure_ascii=False)

        match = await self.get_by_tinder_id(tinder_id)
        now = datetime.now(timezone.utc)
        if match:
            match.name = name or match.name
            if age is not None:
                match.age = age
            if bio is not None:
                match.bio = bio
            if profile_json is not None:
                match.profile_json = profile_json
            if mode is not None:
                match.mode = mode
            match.updated_at = now
        else:
            match = MatchModel(
                tinder_id=tinder_id,
                name=name,
                age=age,
                bio=bio,
                profile_json=profile_json,
                mode=mode or "AUTO",
                created_at=now,
                updated_at=now
            )
            self.session.add(match)
        await self.session.flush()
        return match

    async def list_all(self) -> list[MatchModel]:
        stmt = select(MatchModel).order_by(desc(MatchModel.updated_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_mode(self, tinder_id: str, mode: str) -> None:
        stmt = (
            update(MatchModel)
            .where(MatchModel.tinder_id == tinder_id)
            .values(mode=mode, updated_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_all_modes(self, mode: str) -> int:
        """Update mode for all matches in the database at once."""
        stmt = (
            update(MatchModel)
            .values(mode=mode, updated_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def delete_by_tinder_id(self, tinder_id: str) -> bool:
        """Delete match record by tinder_id."""
        stmt = delete(MatchModel).where(MatchModel.tinder_id == tinder_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (result.rowcount or 0) > 0


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, conversation_id: str) -> ConversationModel | None:
        stmt = select(ConversationModel).where(ConversationModel.conversation_id == conversation_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_match_id(self, match_id: str) -> ConversationModel | None:
        stmt = select(ConversationModel).where(ConversationModel.match_id == match_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert_conversation(
        self,
        conversation_id: str,
        match_id: str,
        summary: str | None = None,
        status: str = "ACTIVE_CHAT"
    ) -> ConversationModel:
        conv = await self.get_by_id(conversation_id)
        now = datetime.now(timezone.utc)
        if conv:
            conv.match_id = match_id
            if summary is not None:
                conv.summary = summary
            conv.status = status
            conv.updated_at = now
        else:
            conv = ConversationModel(
                conversation_id=conversation_id,
                match_id=match_id,
                summary=summary,
                status=status,
                created_at=now,
                updated_at=now
            )
            self.session.add(conv)
        await self.session.flush()
        return conv

    async def update_summary(self, conversation_id: str, summary: str) -> None:
        stmt = (
            update(ConversationModel)
            .where(ConversationModel.conversation_id == conversation_id)
            .values(summary=summary, updated_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_status(self, conversation_id: str, status: str) -> None:
        stmt = (
            update(ConversationModel)
            .where(ConversationModel.conversation_id == conversation_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_by_match_id(self, match_id: str) -> bool:
        stmt = delete(ConversationModel).where(ConversationModel.match_id == match_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (result.rowcount or 0) > 0


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists_by_hash(self, message_hash: str) -> bool:
        stmt = select(func.count(MessageModel.id)).where(MessageModel.message_hash == message_hash)
        result = await self.session.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def add_message(
        self,
        conversation_id: str,
        match_id: str,
        sender: str,
        role: str,
        content: str,
        message_hash: str,
        created_at: datetime | None = None
    ) -> MessageModel | None:
        # Check duplicate
        if await self.exists_by_hash(message_hash):
            logger.debug(f"Message with hash {message_hash[:8]} already exists. Skipping.")
            return None

        msg = MessageModel(
            conversation_id=conversation_id,
            match_id=match_id,
            sender=sender,
            role=role,
            content=content,
            message_hash=message_hash,
            created_at=created_at or datetime.now(timezone.utc)
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_recent_messages(self, conversation_id: str, limit: int = 20) -> list[MessageModel]:
        stmt = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(desc(MessageModel.created_at), desc(MessageModel.id))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        # return in chronological order
        msgs = list(result.scalars().all())
        msgs.reverse()
        return msgs

    async def get_all_messages(self, conversation_id: str) -> list[MessageModel]:
        """All messages of ONE conversation in chronological order (never mixes conversations)."""
        stmt = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at, MessageModel.id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_conversation(self, conversation_id: str) -> int:
        stmt = select(func.count(MessageModel.id)).where(MessageModel.conversation_id == conversation_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def delete_by_match_id(self, match_id: str) -> bool:
        stmt = delete(MessageModel).where(MessageModel.match_id == match_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (result.rowcount or 0) > 0


class MatchProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_match_id(self, match_id: str) -> MatchProfileModel | None:
        stmt = select(MatchProfileModel).where(MatchProfileModel.match_id == match_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def upsert_profile(
        self,
        match_id: str,
        style_json: dict | str | None = None,
        interests_json: list | str | None = None,
        notes_json: dict | str | None = None
    ) -> MatchProfileModel:
        if isinstance(style_json, dict):
            style_json = json.dumps(style_json, ensure_ascii=False)
        if isinstance(interests_json, list):
            interests_json = json.dumps(interests_json, ensure_ascii=False)
        if isinstance(notes_json, dict):
            notes_json = json.dumps(notes_json, ensure_ascii=False)

        profile = await self.get_by_match_id(match_id)
        now = datetime.now(timezone.utc)
        if profile:
            if style_json is not None:
                profile.style_json = style_json
            if interests_json is not None:
                profile.interests_json = interests_json
            if notes_json is not None:
                profile.notes_json = notes_json
            profile.updated_at = now
        else:
            profile = MatchProfileModel(
                match_id=match_id,
                style_json=style_json,
                interests_json=interests_json,
                notes_json=notes_json,
                updated_at=now
            )
            self.session.add(profile)
        await self.session.flush()
        return profile


class AIReplyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_reply(
        self,
        conversation_id: str,
        input_text: str,
        output_text: str,
        status: str = "GENERATED"
    ) -> AIReplyModel:
        reply = AIReplyModel(
            conversation_id=conversation_id,
            input_text=input_text,
            output_text=output_text,
            status=status,
            created_at=datetime.now(timezone.utc)
        )
        self.session.add(reply)
        await self.session.flush()
        return reply

    async def update_status(self, reply_id: int, status: str, sent_at: datetime | None = None) -> None:
        values: dict[str, Any] = {"status": status}
        if sent_at is not None:
            values["sent_at"] = sent_at
        stmt = update(AIReplyModel).where(AIReplyModel.id == reply_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_latest_reply(self, conversation_id: str) -> AIReplyModel | None:
        stmt = (
            select(AIReplyModel)
            .where(AIReplyModel.conversation_id == conversation_id)
            .order_by(desc(AIReplyModel.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
