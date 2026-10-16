"""本地单用户会话和查询轮次；独立于业务元数据。"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    active_context: Mapped[dict | None] = mapped_column(JSON)
    pending_clarification: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConversationDeletion(Base):
    """独立软删除标记，兼容已有会话表，无需修改旧表字段。"""

    __tablename__ = "conversation_deletion"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.id"), primary_key=True
    )
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConversationTurn(Base):
    __tablename__ = "conversation_turn"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.id"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    resolved_query: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    sql: Mapped[str | None] = mapped_column(Text)
    response: Mapped[dict | None] = mapped_column(JSON)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
