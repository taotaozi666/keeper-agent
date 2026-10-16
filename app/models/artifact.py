"""完整查询结果与导出文件的元数据，不把磁盘路径交给模型。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.conversation import utcnow


class Artifact(Base):
    __tablename__ = "artifact"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.id"), index=True
    )
    turn_id: Mapped[str] = mapped_column(ForeignKey("conversation_turn.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(160))
    query: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
