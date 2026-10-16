"""显式启用的本地 MySQL 集成测试；仅新增会话表，清理本测试创建的记录。"""

import os
import unittest

from sqlalchemy import delete

from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.models.conversation import Conversation, ConversationDeletion, ConversationTurn
from app.repositories.mysql.meta.conversation_repository import ConversationRepository


@unittest.skipUnless(
    os.environ.get("KEEPER_TEST_MYSQL") == "1", "需要显式启用本地 MySQL 测试"
)
class MySQLMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_greeting_persists_without_changing_memory(self):
        import json
        from unittest.mock import AsyncMock, patch

        from app.agent.nodes import prepare_query as prepare_module
        from app.services.query_service import QueryService

        async with self.repo.acquire(None, "记忆保护测试") as (
            session,
            conversation,
            turn,
        ):
            cid = conversation.id
            self.ids.append(cid)
            await self.repo.finish(
                session,
                conversation,
                turn,
                {"query": "华南季度销售额", "query_context": {"filters": ["华南"]}},
                {"type": "result", "data": []},
                1,
            )
        async with self.repo.acquire(cid, "按月查询") as (session, conversation, turn):
            await self.repo.finish(
                session,
                conversation,
                turn,
                {"query": "按月查询"},
                {"type": "clarification", "message": "哪一年？"},
                1,
            )
            original_active = conversation.active_context
            original_pending = conversation.pending_clarification
        service = QueryService(None, None, None, None, None, None, self.repo)
        with patch.object(prepare_module, "invoke_model", AsyncMock()) as model:
            for query in ("你好", "谢谢"):
                events = [
                    json.loads(raw.removeprefix("data: "))
                    async for raw in service.query(query, cid)
                ]
                self.assertEqual(events[-1]["type"], "reply")
            model.assert_not_awaited()
        history = await self.repo.history(cid)
        replies = [
            turn for turn in history["turns"] if turn["query"] in ("你好", "谢谢")
        ]
        self.assertEqual(len(replies), 2)
        self.assertTrue(
            all(
                turn["status"] == "reply" and turn["response"]["type"] == "reply"
                for turn in replies
            )
        )
        async with self.repo.acquire(cid, "2025年") as (_, conversation, _):
            self.assertEqual(conversation.active_context, original_active)
            self.assertEqual(conversation.pending_clarification, original_pending)

    async def test_delete_restore_and_busy_guard(self):
        async with self.repo.acquire(None, "删除恢复测试") as (
            session,
            conversation,
            turn,
        ):
            cid = conversation.id
            self.ids.append(cid)
            with self.assertRaisesRegex(ValueError, "正在查询"):
                await self.repo.set_deleted(cid)
            await self.repo.finish(
                session,
                conversation,
                turn,
                {"query": "原问题"},
                {"type": "result", "data": [{"v": 1}]},
                1,
            )
        self.assertTrue(await self.repo.set_deleted(cid))
        self.assertTrue(await self.repo.set_deleted(cid))  # 幂等
        self.assertIsNone(await self.repo.history(cid))
        self.assertNotIn(
            cid,
            [item["id"] for item in (await self.repo.list_conversations(100))["items"]],
        )
        with self.assertRaisesRegex(ValueError, "已删除"):
            async with self.repo.acquire(cid, "不能继续"):
                pass
        self.assertTrue(await self.repo.set_deleted(cid, False))
        history = await self.repo.history(cid)
        self.assertEqual(history["turns"][0]["response"]["data"], [{"v": 1}])
        self.assertIn(
            cid,
            [item["id"] for item in (await self.repo.list_conversations(100))["items"]],
        )

    async def test_list_pagination_and_summary(self):
        for title in ("历史列表测试一", "历史列表测试二"):
            async with self.repo.acquire(None, title) as (session, conversation, turn):
                self.ids.append(conversation.id)
                await self.repo.finish(
                    session, conversation, turn, {}, {"type": "result", "data": []}, 1
                )
        first = await self.repo.list_conversations(limit=1, offset=0)
        second = await self.repo.list_conversations(limit=1, offset=1)
        combined = await self.repo.list_conversations(limit=2, offset=0)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["items"] + second["items"], combined["items"])
        self.assertGreaterEqual(
            first["items"][0]["updated_at"], second["items"][0]["updated_at"]
        )
        self.assertEqual(set(first["items"][0]), {"id", "title", "updated_at"})
        self.assertTrue(first["items"][0]["updated_at"].endswith("Z"))

    async def asyncSetUp(self):
        meta_mysql_client_manager.init()
        self.repo = ConversationRepository(meta_mysql_client_manager.engine)
        await self.repo.initialize()
        self.ids = []

    async def asyncTearDown(self):
        async with meta_mysql_client_manager.session_factory() as session:
            await session.execute(
                delete(ConversationDeletion).where(
                    ConversationDeletion.conversation_id.in_(self.ids)
                )
            )
            await session.execute(
                delete(ConversationTurn).where(
                    ConversationTurn.conversation_id.in_(self.ids)
                )
            )
            await session.execute(
                delete(Conversation).where(Conversation.id.in_(self.ids))
            )
            await session.commit()
        await meta_mysql_client_manager.close()

    async def test_persistence_lock_isolation_and_failure(self):
        async with self.repo.acquire(None, "测试会话") as (session, conversation, turn):
            cid = conversation.id
            self.ids.append(cid)
            with self.assertRaisesRegex(ValueError, "正在查询"):
                async with self.repo.acquire(cid, "并发"):
                    self.fail("不应获取锁")
            await self.repo.finish(
                session,
                conversation,
                turn,
                {
                    "query": "2025年3月华东销售额",
                    "query_context": {"filters": ["华东"]},
                    "sql": "SELECT 1",
                },
                {"type": "result", "data": []},
                10,
            )
        history = await self.repo.history(cid)
        self.assertEqual(history["turns"][0]["status"], "success")
        self.assertEqual(history["turns"][0]["response"]["data"], [])
        async with self.repo.acquire(cid, "失败问题") as (session, conversation, turn):
            self.assertEqual(
                conversation.active_context["resolved_query"], "2025年3月华东销售额"
            )
            await session.rollback()  # 验证失败清理后仍可保存记录
            await self.repo.finish(
                session,
                conversation,
                turn,
                {},
                {"type": "error", "message": "模拟失败"},
                10,
            )
        async with self.repo.acquire(None, "另一会话") as (session, conversation, turn):
            self.ids.append(conversation.id)
            self.assertIsNone(conversation.active_context)
        async with self.repo.acquire(cid, "需要澄清") as (session, conversation, turn):
            self.assertEqual(
                conversation.active_context["resolved_query"], "2025年3月华东销售额"
            )
            await self.repo.finish(
                session,
                conversation,
                turn,
                {"query": "订单量"},
                {"type": "clarification", "message": "哪个月？"},
                10,
            )
        async with self.repo.acquire(cid, "三月") as (_, conversation, _):
            self.assertEqual(conversation.pending_clarification["question"], "哪个月？")

    async def test_service_saves_before_result_and_releases_lock(self):
        from app.services.query_service import QueryService

        class FakeService(QueryService):
            async def _events(inner, state):
                state.update(query="补全问题", query_context={"metrics": ["订单量"]})
                yield {"type": "result", "data": []}

        import json

        service = FakeService(None, None, None, None, None, None, self.repo)
        stream = service.query("测试问题")
        first = json.loads((await anext(stream)).removeprefix("data: "))
        cid = first["conversation_id"]
        self.ids.append(cid)
        result = json.loads((await anext(stream)).removeprefix("data: "))
        self.assertEqual(result["type"], "result")
        self.assertEqual(
            (await self.repo.history(cid))["turns"][0]["status"], "success"
        )
        # 外层生成器尚未关闭，但连接锁已释放。
        async with self.repo.acquire(cid, "下一轮"):
            pass
        await stream.aclose()

    async def test_cancel_after_conversation_event_is_recorded(self):
        import json

        from app.services.query_service import QueryService

        service = QueryService(None, None, None, None, None, None, self.repo)
        stream = service.query("取消测试")
        cid = json.loads((await anext(stream)).removeprefix("data: "))[
            "conversation_id"
        ]
        self.ids.append(cid)
        await stream.aclose()
        self.assertEqual((await self.repo.history(cid))["turns"][0]["status"], "failed")
        async with self.repo.acquire(cid, "可再次获取"):
            pass
