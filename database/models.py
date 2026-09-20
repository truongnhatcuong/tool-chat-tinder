"""SQLAlchemy database models for Tinder AI Assistant."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Index
)
from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class MatchModel(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tinder_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    age = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    profile_json = Column(Text, nullable=True)
    mode = Column(String(32), default="AUTO", nullable=False)  # OFF, SUGGEST, AUTO
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<Match(id={self.id}, tinder_id='{self.tinder_id}', name='{self.name}', mode='{self.mode}')>"


class ConversationModel(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(128), unique=True, nullable=False, index=True)
    match_id = Column(String(128), nullable=False, index=True)
    summary = Column(Text, nullable=True)
    status = Column(String(64), default="ACTIVE_CHAT", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, conversation_id='{self.conversation_id}', status='{self.status}')>"


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(128), nullable=False, index=True)
    match_id = Column(String(128), nullable=False, index=True)
    sender = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)  # incoming, outgoing, system
    content = Column(Text, nullable=False)
    message_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_conv_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, sender='{self.sender}', role='{self.role}')>"


class MatchProfileModel(Base):
    __tablename__ = "match_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String(128), unique=True, nullable=False, index=True)
    style_json = Column(Text, nullable=True)
    interests_json = Column(Text, nullable=True)
    notes_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<MatchProfile(id={self.id}, match_id='{self.match_id}')>"


class AIReplyModel(Base):
    __tablename__ = "ai_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(128), nullable=False, index=True)
    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=False)
    status = Column(String(32), default="GENERATED", nullable=False)  # GENERATED, APPROVED, SENT, REJECTED, FAILED
    created_at = Column(DateTime, default=utc_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<AIReply(id={self.id}, conversation_id='{self.conversation_id}', status='{self.status}')>"
