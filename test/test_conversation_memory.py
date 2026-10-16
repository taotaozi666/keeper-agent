"""离线测试真实 Graph 分支和会话提交规则，不调用模型服务。"""

import types
import unittest
from unittest.mock import AsyncMock, patch

from app.repositories.mysql.meta.conversation_repository import (
    ConversationRepository,
    snapshot,
)
from test.test_agent_workflow import graph, prepare_module


def prepared(**changes):
    values = dict(
        column_terms=["月份"],
        metric_terms=["销售额"],
        value_terms=["华东"],
        relation="follow_up",
        resolved_query="统计2025年3月华东销售额",
        query_context={
            "metrics": ["销售额"],
            "time_range": "2025年3月",
            "filters": ["大区=华东"],
        },
        action="query",
        reply_text="",
    )
    values.update(changes)
    return prepare_module.PreparedQuery(**values)


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_greetings_end_graph_without_model_or_retrieval(self):
        for query in ("你好", " 您好！ ", "HELLO!", "谢谢。", "辛苦了", "再见"):
            with (
                self.subTest(query=query),
                patch.object(prepare_module, "invoke_model", AsyncMock()) as model,
            ):
                events = [
                    event
                    async for event in graph.astream(
                        {
                            "query": query,
                            "memory_enabled": True,
                            "conversation_context": {
                                "active": {"metrics": ["销售额"]},
                                "pending": {"question": "哪个年？"},
                            },
                        },
                        context={},
                        stream_mode="custom",
                    )
                ]
                model.assert_not_awaited()
                self.assertEqual(events[-1]["type"], "reply")
                self.assertFalse(
                    any(e["type"] in ("result", "clarification") for e in events)
                )

    async def test_mixed_greeting_and_context_sensitive_short_answers_use_model(self):
        for query in ("你好，查一下华东销售额", "好的", "可以", "继续", "就这个"):
            with (
                self.subTest(query=query),
                patch.object(
                    prepare_module, "invoke_model", AsyncMock(return_value=prepared())
                ) as model,
            ):
                result = await prepare_module.prepare_query(
                    {
                        "query": query,
                        "memory_enabled": True,
                        "conversation_context": {"pending": {"question": "哪个年？"}},
                    },
                    types.SimpleNamespace(stream_writer=lambda _: None),
                )
                model.assert_awaited_once()
                self.assertEqual(result["action"], "query")
                self.assertIn("哪个年", model.await_args.args[3]["memory"])

    async def test_model_reply_ends_graph_after_one_call(self):
        from langchain_core.runnables import RunnableLambda

        calls = []

        def respond(prompt, **kwargs):
            calls.append(prompt.to_string())
            return prepare_module.PreparedQuery(
                action="reply",
                reply_text="我可以帮助你查询数据库、连续追问和恢复历史会话。",
                relation=None,
                resolved_query=None,
                query_context=None,
                column_terms=[],
                metric_terms=[],
                value_terms=[],
            ).model_dump_json()

        with patch.object(prepare_module, "llm", RunnableLambda(respond)):
            events = [
                event
                async for event in graph.astream(
                    {"query": "你能做些什么？", "memory_enabled": True},
                    context={},
                    stream_mode="custom",
                )
            ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(events[-1]["type"], "reply")

    def test_invalid_branch_combinations_are_rejected(self):
        from pydantic import ValidationError

        for changes in (
            {"action": "reply", "reply_text": "你好"},  # 携带查询条件
            {"action": "query", "reply_text": "直接回答"},
            {
                "action": "clarify",
                "reply_text": "",
                "column_terms": [],
                "metric_terms": [],
                "value_terms": [],
            },
            {"resolved_query": "   "},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                prepared(**changes)

    async def test_reply_preserves_active_and_pending_memory(self):
        repo, session, conversation, turn = self.persistence_objects()
        await repo.finish(
            session,
            conversation,
            turn,
            {"query": "谢谢", "action": "reply"},
            {"type": "reply", "message": "不客气。"},
            1,
        )
        self.assertEqual(conversation.active_context, {"old": True})
        self.assertEqual(conversation.pending_clarification, {"pending": True})
        self.assertEqual(turn.status, "reply")
        self.assertIsNone(turn.sql)
        self.assertEqual(turn.response["type"], "reply")

    async def test_full_graph_uses_resolved_query_with_three_calls(self):
        import json

        from langchain_core.runnables import RunnableLambda

        from test import test_agent_workflow as workflow

        fixture = workflow.WorkflowTests()
        fixture.setUp()
        calls = []

        async def respond(prompt, **kwargs):
            value = prompt.to_string()
            calls.append(value)
            if "当前日期：" in value:
                return prepared().model_dump_json()
            if "联合选择回答所需" in value:
                return json.dumps({"tables": {"fact": ["id"]}, "metrics": ["total"]})
            return "select sum(amount) as total from fact"

        model = RunnableLambda(respond)
        with (
            patch.object(prepare_module, "llm", model),
            patch.object(workflow.select_module, "llm", model),
            patch.object(workflow.generate_module, "llm", model),
        ):
            events = [
                e
                async for e in graph.astream(
                    {
                        "query": "只看华东",
                        "memory_enabled": True,
                        "conversation_context": {
                            "active": {"resolved_query": "统计2025年3月销售额"}
                        },
                    },
                    context=fixture.context,
                    stream_mode="custom",
                )
            ]
        self.assertEqual(len(calls), 3)
        self.assertIn("统计2025年3月华东销售额", calls[1])
        self.assertIn("统计2025年3月华东销售额", calls[2])
        self.assertEqual(events[-1]["type"], "result")

    async def test_followup_rewrites_query_and_retrieval_terms(self):
        model = AsyncMock(return_value=prepared())
        state = {
            "query": "只看华东",
            "keywords": ["只看"],
            "memory_enabled": True,
            "conversation_context": {
                "active": {"resolved_query": "统计2025年3月销售额"}
            },
        }
        with patch.object(prepare_module, "invoke_model", model):
            result = await prepare_module.prepare_query(
                state, types.SimpleNamespace(stream_writer=lambda _: None)
            )
        self.assertEqual(result["query"], "统计2025年3月华东销售额")
        self.assertNotIn("只看", result["column_terms"])
        self.assertIn("2025年3月", model.await_args.args[3]["memory"])
        self.assertEqual(
            prepare_module.route_after_prepare(result), ["embed_terms", "recall_value"]
        )

    async def test_clarification_ends_real_graph_before_retrieval(self):
        with patch.object(
            prepare_module,
            "invoke_model",
            AsyncMock(
                return_value=prepared(
                    action="clarify",
                    reply_text="请问查询哪个月份？",
                    column_terms=[],
                    metric_terms=[],
                    value_terms=[],
                )
            ),
        ):
            events = [
                event
                async for event in graph.astream(
                    {"query": "那个呢", "memory_enabled": True},
                    context={},
                    stream_mode="custom",
                )
            ]
        self.assertEqual(
            events[-1], {"type": "clarification", "message": "请问查询哪个月份？"}
        )
        self.assertFalse(any(e.get("type") == "result" for e in events))

    async def test_invalid_memory_output_never_falls_back_to_incomplete_query(self):
        with patch.object(
            prepare_module, "invoke_model", AsyncMock(side_effect=ValueError("invalid"))
        ):
            with self.assertRaisesRegex(ValueError, "问题理解失败"):
                await prepare_module.prepare_query(
                    {"query": "只看华东", "memory_enabled": True},
                    types.SimpleNamespace(stream_writer=lambda _: None),
                )

    async def test_pending_clarification_reaches_model(self):
        model = AsyncMock(return_value=prepared())
        with patch.object(prepare_module, "invoke_model", model):
            await prepare_module.prepare_query(
                {
                    "query": "2025年3月",
                    "memory_enabled": True,
                    "conversation_context": {
                        "pending": {"query": "统计华东销售额", "question": "哪个月份？"}
                    },
                },
                types.SimpleNamespace(stream_writer=lambda _: None),
            )
        self.assertIn("哪个月份", model.await_args.args[3]["memory"])

    async def test_success_empty_result_updates_context(self):
        repo, session, conversation, turn = self.persistence_objects()
        await repo.finish(
            session,
            conversation,
            turn,
            {"query": "四月订单", "query_context": {"time_range": "四月"}},
            {"type": "result", "data": []},
            12,
        )
        self.assertEqual(conversation.active_context["resolved_query"], "四月订单")
        self.assertIsNone(conversation.pending_clarification)
        self.assertEqual(turn.status, "success")
        session.commit.assert_awaited_once()

    async def test_failure_does_not_overwrite_memory(self):
        repo, session, conversation, turn = self.persistence_objects()
        await repo.finish(
            session,
            conversation,
            turn,
            {"query": "新问题"},
            {"type": "error", "message": "timeout"},
            10,
        )
        self.assertEqual(conversation.active_context, {"old": True})
        self.assertEqual(conversation.pending_clarification, {"pending": True})

    async def test_clarification_preserves_active_and_saves_pending(self):
        repo, session, conversation, turn = self.persistence_objects()
        await repo.finish(
            session,
            conversation,
            turn,
            {"query": "华东销售额"},
            {"type": "clarification", "message": "哪个月？"},
            10,
        )
        self.assertEqual(conversation.active_context, {"old": True})
        self.assertEqual(conversation.pending_clarification["question"], "哪个月？")

    def persistence_objects(self):
        return (
            ConversationRepository(None),
            types.SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock()),
            types.SimpleNamespace(
                active_context={"old": True},
                pending_clarification={"pending": True},
                version=0,
            ),
            types.SimpleNamespace(query="test"),
        )

    def test_snapshots_are_bounded_and_marked(self):
        value = snapshot({"type": "result", "data": [{"v": n} for n in range(120)]})
        self.assertEqual(len(value["data"]), 100)
        self.assertEqual(value["row_count"], 120)
        self.assertTrue(value["truncated"])
        large = snapshot({"type": "result", "data": [{"v": "x" * 70000}]})
        self.assertEqual(large["data"], [])
        self.assertTrue(large["truncated"])

    async def test_service_consumes_state_updates_before_terminal(self):
        import app.services.query_service as service_module
        from app.services.query_service import QueryService

        class FakeGraph:
            async def astream(self, **kwargs):
                yield "custom", {"type": "clarification", "message": "哪个月？"}
                yield (
                    "updates",
                    {
                        "prepare_query": {
                            "query": "补全后的问题",
                            "query_context": {"metrics": ["金额"]},
                        }
                    },
                )

        state = {"query": "原问题"}
        with patch.object(service_module, "graph", FakeGraph()):
            events = [
                e
                async for e in QueryService(None, None, None, None, None, None)._events(
                    state
                )
            ]
        self.assertEqual(state["query"], "补全后的问题")
        self.assertEqual(events[-1]["type"], "clarification")
