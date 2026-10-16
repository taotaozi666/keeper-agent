"""会话使用独立连接；MySQL 命名锁覆盖多个应用进程。"""

import json
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import (
    Conversation,
    ConversationDeletion,
    ConversationTurn,
    utcnow,
)


def snapshot(event):
    result = json.loads(json.dumps(event, ensure_ascii=False, default=str))
    if result.get("type") == "done":
        result["results"] = [
            {**item, **snapshot({"type": "result", "data": item["data"]})}
            for item in result.get("results", [])
        ]
    if result.get("type") == "result":
        rows = result["data"]
        kept = []
        size = 0
        for row in rows[:100]:
            size += len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
            if size > 65536:
                break
            kept.append(row)
        result.update(data=kept, row_count=len(rows), truncated=len(kept) < len(rows))
    return result


class ConversationRepository:
    def __init__(self, engine):
        self.engine = engine

    async def initialize(self):
        async with self.engine.begin() as conn:
            for table in (
                Conversation.__table__,
                ConversationTurn.__table__,
                ConversationDeletion.__table__,
            ):
                await conn.run_sync(
                    lambda sync, t=table: t.create(sync, checkfirst=True)
                )

    @asynccontextmanager
    async def acquire(self, conversation_id, query):
        cid = conversation_id or str(uuid4())
        async with self.engine.connect() as conn:
            acquired = await conn.scalar(
                text("SELECT GET_LOCK(:name, 0)"), {"name": f"keeper:{cid}"}
            )
            await conn.commit()
            if acquired != 1:
                raise ValueError("该会话正在查询，请等待完成后重试。")
            try:
                async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                    conversation = await session.get(Conversation, cid)
                    if await session.get(ConversationDeletion, cid) is not None:
                        raise ValueError("会话已删除，请新建会话。")
                    if conversation_id and conversation is None:
                        raise ValueError("会话不存在，请新建会话。")
                    if conversation is None:
                        conversation = Conversation(id=cid, title=query[:200])
                        session.add(conversation)
                    # 持有命名锁说明旧 running 轮次已失去执行者（断连或进程退出）。
                    await session.execute(
                        update(ConversationTurn)
                        .where(
                            ConversationTurn.conversation_id == cid,
                            ConversationTurn.status == "running",
                        )
                        .values(
                            status="cancelled",
                            response={"type": "error", "message": "上次查询已中断。"},
                        )
                    )
                    turn = ConversationTurn(
                        id=str(uuid4()),
                        conversation_id=cid,
                        query=query,
                        status="running",
                    )
                    session.add(turn)
                    await session.commit()
                    yield session, conversation, turn
            finally:
                # 取消时也必须释放连接级锁；失效连接由 MySQL 自动释放。
                import anyio

                with anyio.CancelScope(shield=True):
                    await conn.rollback()
                    await conn.execute(
                        text("SELECT RELEASE_LOCK(:name)"), {"name": f"keeper:{cid}"}
                    )
                    await conn.commit()

    async def finish(self, session, conversation, turn, state, event, elapsed_ms):
        await session.refresh(conversation)
        await session.refresh(turn)
        turn.status = {
            "result": "success",
            "clarification": "clarification",
            "reply": "reply",
            "done": "success",
        }.get(event["type"], "failed")
        if event["type"] == "done" and event.get("error"):
            turn.status = (
                "partial" if event.get("results") or event.get("files") else "failed"
            )
        turn.resolved_query = state.get("query", turn.query)
        turn.sql = state.get("sql")
        turn.response = snapshot(event)
        turn.elapsed_ms = int(elapsed_ms)
        if event["type"] == "result":
            conversation.active_context = {
                "resolved_query": turn.resolved_query,
                "conditions": state.get("query_context", {}),
                "result_preview": snapshot(
                    {"type": "result", "data": event["data"][:3]}
                )["data"],
            }
            conversation.pending_clarification = None
        elif event["type"] == "clarification":
            conversation.pending_clarification = {
                "query": turn.resolved_query,
                "conditions": state.get("query_context", {}),
                "question": event["message"],
            }
        if event["type"] == "done":
            last_query = state.get("last_query")
            if last_query:
                child = last_query["state"]
                turn.sql = child.get("sql")
                turn.resolved_query = child["query"]
                conversation.active_context = {
                    "resolved_query": child["query"],
                    "conditions": child.get("query_context", {}),
                    "query_result_id": last_query["query_result_id"],
                    "result_preview": snapshot(
                        {"type": "result", "data": last_query["data"][:3]}
                    )["data"],
                }
                conversation.pending_clarification = None
            pending = state.get("pending_query")
            if pending:
                turn.status = "clarification"
                conversation.pending_clarification = {
                    "query": pending["state"]["query"],
                    "conditions": pending["state"].get("query_context", {}),
                    "question": pending["message"],
                }
        conversation.version += 1
        conversation.updated_at = utcnow()
        await session.commit()

    async def set_deleted(self, cid, deleted=True):
        async with self.engine.connect() as conn:
            acquired = await conn.scalar(
                text("SELECT GET_LOCK(:name, 0)"), {"name": f"keeper:{cid}"}
            )
            await conn.commit()
            if acquired != 1:
                raise ValueError("该会话正在查询，请结束查询后再操作。")
            try:
                async with AsyncSession(bind=conn) as session:
                    if await session.get(Conversation, cid) is None:
                        return False
                    marker = await session.get(ConversationDeletion, cid)
                    if deleted and marker is None:
                        session.add(ConversationDeletion(conversation_id=cid))
                    elif not deleted and marker is not None:
                        await session.delete(marker)
                    await session.commit()
                    return True
            finally:
                import anyio

                with anyio.CancelScope(shield=True):
                    await conn.rollback()
                    await conn.execute(
                        text("SELECT RELEASE_LOCK(:name)"), {"name": f"keeper:{cid}"}
                    )
                    await conn.commit()

    async def list_conversations(self, limit=30, offset=0):
        async with AsyncSession(self.engine) as session:
            rows = (
                await session.execute(
                    select(Conversation.id, Conversation.title, Conversation.updated_at)
                    .where(
                        ~select(ConversationDeletion.conversation_id)
                        .where(ConversationDeletion.conversation_id == Conversation.id)
                        .exists()
                    )
                    .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            return {
                "items": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "updated_at": row.updated_at.isoformat() + "Z",
                    }
                    for row in rows[:limit]
                ],
                "has_more": len(rows) > limit,
            }

    async def history(self, cid):
        async with AsyncSession(self.engine) as session:
            conversation = await session.get(Conversation, cid)
            if (
                conversation is None
                or await session.get(ConversationDeletion, cid) is not None
            ):
                return None
            turns = (
                await session.scalars(
                    select(ConversationTurn)
                    .where(ConversationTurn.conversation_id == cid)
                    .order_by(ConversationTurn.created_at, ConversationTurn.id)
                )
            ).all()
            return {
                "id": cid,
                "title": conversation.title,
                "turns": [
                    {
                        "id": t.id,
                        "query": t.query,
                        "status": t.status,
                        "response": t.response,
                        "created_at": t.created_at.isoformat() + "Z",
                    }
                    for t in turns
                ],
            }
