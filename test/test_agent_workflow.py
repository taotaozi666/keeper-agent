"""离线工作流回归：无需本地凭据、模型接口或数据库。

运行：python -m unittest test.test_agent_workflow -v
"""

import asyncio
import importlib
import json
import os
import sys
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableLambda
from omegaconf import OmegaConf

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo

# 使用公开模板加载配置，避免测试依赖被忽略的本地文件和真实模型凭据。
original_load = OmegaConf.load
template = Path(__file__).resolve().parents[1] / "conf/app_config.example.yaml"


def load_test_config(path):
    if Path(path).name == "app_config.yaml":
        return original_load(template)
    return original_load(path)


fake_llm = types.ModuleType("app.agent.llm")
fake_llm.llm = RunnableLambda(lambda _: "")
previous_llm_module = sys.modules.get("app.agent.llm")
sys.modules["app.agent.llm"] = fake_llm
with (
    patch.dict(
        os.environ,
        {
            "LLM_MODEL_NAME": "test",
            "LLM_API_KEY": "test",
            "LLM_BASE_URL": "http://localhost/v1",
        },
    ),
    patch.object(OmegaConf, "load", side_effect=load_test_config),
):
    graph = importlib.import_module("app.agent.graph").graph
    prepare_module = importlib.import_module("app.agent.nodes.prepare_query")
    select_module = importlib.import_module("app.agent.nodes.select_context")
    generate_module = importlib.import_module("app.agent.nodes.generate_sql")
    correct_module = importlib.import_module("app.agent.nodes.correct_sql")
if previous_llm_module is None:
    sys.modules.pop("app.agent.llm", None)
else:
    sys.modules["app.agent.llm"] = previous_llm_module


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.amount = ColumnInfo(
            "fact.amount", "amount", "decimal", "measure", [], "金额", [], "fact"
        )
        self.key = ColumnInfo(
            "fact.id", "id", "int", "primary_key", [], "主键", [], "fact"
        )
        self.metric = MetricInfo("total", "total", "金额总和", ["fact.amount"], [])
        self.dw = types.SimpleNamespace(
            get_db_info=AsyncMock(return_value={"dialect": "mysql", "version": "8.0"}),
            validate=AsyncMock(),
            run=AsyncMock(return_value=[{"total": 10}]),
        )
        self.context = {
            "embedding_client": types.SimpleNamespace(
                aembed_documents=AsyncMock(
                    side_effect=lambda terms: [[0.1] for _ in terms]
                )
            ),
            "column_qdrant_repository": types.SimpleNamespace(
                search=AsyncMock(return_value=[self.amount])
            ),
            "metric_qdrant_repository": types.SimpleNamespace(
                search=AsyncMock(return_value=[self.metric])
            ),
            "value_es_repository": types.SimpleNamespace(
                search=AsyncMock(return_value=[])
            ),
            "meta_mysql_repository": types.SimpleNamespace(
                get_column_info_by_id=AsyncMock(return_value=self.amount),
                get_key_columns_by_table_id=AsyncMock(return_value=[self.key]),
                get_table_info_by_id=AsyncMock(
                    return_value=TableInfo("fact", "fact", "fact", "事实表")
                ),
            ),
            "dw_mysql_repository": self.dw,
        }

    async def execute(self, *, malformed_expansion=False, invalid_selection=False):
        calls = []

        async def respond(prompt):
            text = prompt.to_string()
            calls.append(text)
            if "一次性生成用于三路检索" in text:
                if malformed_expansion:
                    return '{"column_terms": "错误结构"}'
                return json.dumps(
                    {
                        "column_terms": ["金额"],
                        "metric_terms": ["总额"],
                        "value_terms": [],
                    }
                )
            if "联合选择回答所需" in text:
                return json.dumps(
                    {
                        "tables": {"unknown" if invalid_selection else "fact": ["id"]},
                        "metrics": ["total"],
                    }
                )
            return "select sum(amount) as total from fact"

        model = RunnableLambda(respond)
        events = []
        with (
            patch.object(prepare_module, "llm", model),
            patch.object(select_module, "llm", model),
            patch.object(generate_module, "llm", model),
            patch.object(correct_module, "llm", model),
        ):
            async for event in graph.astream(
                {"query": "统计总额"},
                context=self.context,
                stream_mode="custom",
            ):
                events.append(event)
        return calls, events

    async def test_normal_path_uses_three_model_calls(self):
        calls, events = await self.execute()
        self.assertEqual(len(calls), 3)
        embeddings = self.context["embedding_client"].aembed_documents
        embeddings.assert_awaited_once()
        batch = embeddings.await_args.args[0]
        self.assertEqual(len(batch), len(set(batch)))
        self.assertEqual(
            [e["data"] for e in events if e["type"] == "result"], [[{"total": 10}]]
        )
        self.dw.validate.assert_awaited_once()
        self.dw.run.assert_awaited_once()
        # 筛选仅选 id，但生成提示词必须仍包含指标依赖 amount。
        self.assertIn("name: amount", calls[-1])

    async def test_invalid_expansion_falls_back_and_completes(self):
        calls, events = await self.execute(malformed_expansion=True)
        self.assertEqual(len(calls), 3)
        self.assertTrue(any(e["type"] == "result" for e in events))
        searched = self.context["embedding_client"].aembed_documents.await_args_list
        self.assertTrue(any("统计总额" in call.args[0] for call in searched))

    async def test_repaired_sql_is_validated_before_execution(self):
        self.dw.validate.side_effect = [ValueError("unknown column"), None]
        calls, _ = await self.execute()
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.dw.validate.await_count, 2)
        self.dw.run.assert_awaited_once()

    async def test_repair_limit_never_executes_invalid_sql(self):
        self.dw.validate.side_effect = ValueError("invalid SQL")
        with self.assertRaisesRegex(ValueError, "2 次修复上限"):
            await self.execute()
        self.assertEqual(self.dw.validate.await_count, 3)
        self.dw.run.assert_not_awaited()

    async def test_unknown_selection_stops_before_sql_execution(self):
        with self.assertRaisesRegex(ValueError, "未知候选表"):
            await self.execute(invalid_selection=True)
        self.dw.validate.assert_not_awaited()
        self.dw.run.assert_not_awaited()

    def test_dependency_table_and_keys_are_restored_without_mutating_input(self):
        state = {
            "table_infos": [
                {
                    "name": "fact",
                    "role": "fact",
                    "description": "",
                    "columns": [
                        {"name": "id", "role": "primary_key"},
                        {"name": "amount", "role": "measure"},
                        {"name": "unused", "role": "dimension"},
                    ],
                }
            ],
            "metric_infos": [{"name": "total", "relevant_columns": ["fact.amount"]}],
        }
        original = deepcopy(state)
        selected = select_module.ContextSelection(tables={}, metrics=["total"])
        result = select_module.apply_selection(state, selected)
        self.assertEqual(
            [c["name"] for c in result["table_infos"][0]["columns"]], ["id", "amount"]
        )
        self.assertEqual(state, original)

    async def test_shared_vectors_are_batched_and_reused_across_branches(self):
        module = importlib.import_module("app.agent.nodes.embed_terms")
        terms = [f"term_{i}" for i in range(25)]
        events = []
        runtime = types.SimpleNamespace(
            context=self.context, stream_writer=events.append
        )
        result = await module.embed_terms(
            {"column_terms": terms, "metric_terms": terms}, runtime
        )
        self.assertEqual(len(result["term_embeddings"]), 25)
        requests = self.context["embedding_client"].aembed_documents.await_args_list
        self.assertEqual([len(call.args[0]) for call in requests], [20, 5])

    async def test_wrong_embedding_count_stops_workflow(self):
        self.context["embedding_client"].aembed_documents.side_effect = lambda terms: []
        with self.assertRaisesRegex(ValueError, "向量数量不匹配"):
            await self.execute()
        self.dw.run.assert_not_awaited()

    async def test_retrieval_concurrency_is_bounded_and_order_is_stable(self):
        from app.agent.retrieval import SEARCH_CONCURRENCY, bounded_map

        entered = 0
        active = 0
        peak = 0
        full = asyncio.Event()
        release = asyncio.Event()

        async def operation(item):
            nonlocal entered, active, peak
            entered += 1
            active += 1
            peak = max(peak, active)
            if entered == SEARCH_CONCURRENCY:
                full.set()
            await release.wait()
            active -= 1
            return item * 2

        task = asyncio.create_task(bounded_map(list(range(12)), operation))
        await asyncio.wait_for(full.wait(), timeout=2)
        self.assertEqual(entered, SEARCH_CONCURRENCY)
        release.set()
        self.assertEqual(await task, [item * 2 for item in range(12)])
        self.assertEqual(peak, SEARCH_CONCURRENCY)

    async def test_retrieval_failure_cancels_pending_requests(self):
        from app.agent.retrieval import bounded_map

        active = 0

        async def operation(item):
            nonlocal active
            active += 1
            try:
                if item == 0:
                    raise ValueError("search failed")
                await asyncio.Event().wait()
            finally:
                active -= 1

        with self.assertRaisesRegex(ValueError, "search failed"):
            await bounded_map(list(range(8)), operation)
        self.assertEqual(active, 0)

    async def test_model_usage_is_logged_without_extra_model_calls(self):
        from langchain_core.messages import AIMessage
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import PromptTemplate

        from app.agent.observability import invoke_model

        async def respond(_):
            return AIMessage(
                content="SELECT 1",
                usage_metadata={
                    "input_tokens": 8,
                    "output_tokens": 2,
                    "total_tokens": 10,
                },
            )

        messages = []
        from app.core.log import logger

        sink = logger.add(lambda message: messages.append(str(message)))
        try:
            result = await invoke_model(
                PromptTemplate.from_template("{query}"),
                RunnableLambda(respond),
                StrOutputParser(),
                {"query": "test"},
                stage="test",
            )
        finally:
            logger.remove(sink)
        self.assertEqual(result, "SELECT 1")
        self.assertTrue(
            any(
                "input_tokens=8 output_tokens=2 total_tokens=10" in message
                for message in messages
            )
        )

    def test_only_optimizer_notes_are_filtered(self):
        import logging

        from app.core.db_logging import ExplainNoteFilter

        def record(message):
            return logging.LogRecord(
                "asyncmy", logging.WARNING, "", 0, message, (), None
            )

        filter_ = ExplainNoteFilter()
        self.assertFalse(filter_.filter(record("/* select#1 */ select 1")))
        self.assertTrue(filter_.filter(record("Data truncated for column")))

    async def test_full_conversation_logging_is_opt_in_and_preserves_messages(self):
        from langchain_core.messages import AIMessage
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        from app.agent.observability import invoke_model
        from app.conf.app_config import app_config
        from app.core.log import logger

        async def respond(prompt):
            self.assertEqual(
                prompt.to_messages()[1].content, "问题：测试\n上下文：完整表结构"
            )
            return AIMessage(
                content="SELECT 1;",
                additional_kwargs={"reasoning_content": "接口返回的说明"},
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "使用提供的上下文"),
                ("human", "问题：{query}\n上下文：{context}"),
            ]
        )
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                messages = []
                sink = logger.add(lambda message: messages.append(str(message)))
                try:
                    with (
                        patch.object(app_config.llm, "log_conversations", enabled),
                        patch.object(
                            app_config.llm, "api_key", "credential-not-logged-123"
                        ),
                    ):
                        result = await invoke_model(
                            prompt,
                            RunnableLambda(respond),
                            StrOutputParser(),
                            {"query": "测试", "context": "完整表结构"},
                            stage="test_conversation",
                        )
                finally:
                    logger.remove(sink)
                self.assertEqual(result, "SELECT 1;")
                trace = "\n".join(messages)
                self.assertEqual("LLM_INPUT" in trace, enabled)
                self.assertEqual("LLM_OUTPUT" in trace, enabled)
                if enabled:
                    self.assertIn("[system]", trace)
                    self.assertIn("问题：测试\n上下文：完整表结构", trace)
                    self.assertIn("接口返回的说明", trace)
                    self.assertIn("SELECT 1;", trace)
                    self.assertNotIn("credential-not-logged-123", trace)

    async def test_raw_response_logged_even_when_parsing_fails(self):
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import PromptTemplate

        from app.agent.observability import invoke_model
        from app.conf.app_config import app_config
        from app.core.log import logger

        messages = []
        sink = logger.add(lambda message: messages.append(str(message)))
        try:
            with patch.object(app_config.llm, "log_conversations", True):
                with self.assertRaises(Exception):
                    await invoke_model(
                        PromptTemplate.from_template("{query}"),
                        RunnableLambda(lambda _: "invalid-json-output"),
                        JsonOutputParser(),
                        {"query": "test"},
                        stage="parse_failure",
                    )
        finally:
            logger.remove(sink)
        self.assertTrue(
            any(
                "LLM_OUTPUT" in message and "invalid-json-output" in message
                for message in messages
            )
        )

    def test_column_json_arrays_are_normalized_and_invalid_types_rejected(self):
        column = ColumnInfo(
            "t.id", "id", "int", "primary_key", "[1, 2]", "", '["编号"]', "t"
        )
        self.assertEqual(column.examples, [1, 2])
        self.assertEqual(column.alias, ["编号"])
        with self.assertRaisesRegex(ValueError, "必须是数组"):
            ColumnInfo("t.id", "id", "int", "primary_key", "{}", "", [], "t")

    def test_prompt_samples_are_compact_without_losing_recalled_values(self):
        from app.agent.prompt_context import prompt_tables
        from app.entities.value_info import ValueInfo

        state = {
            "table_infos": [
                {
                    "name": "t",
                    "columns": [
                        {
                            "name": "id",
                            "role": "primary_key",
                            "examples": list(range(10)),
                        },
                        {
                            "name": "amount",
                            "role": "measure",
                            "examples": list(range(10)),
                        },
                        {
                            "name": "region",
                            "role": "dimension",
                            "examples": ["a", "b", "c", "d"],
                        },
                    ],
                }
            ],
            "retrieved_value_infos": [ValueInfo("hit", "d", "t.region")],
        }
        original = deepcopy(state)
        columns = prompt_tables(state)[0]["columns"]
        self.assertEqual(columns[0]["examples"], [])
        self.assertEqual(columns[1]["examples"], [])
        self.assertEqual(columns[2]["examples"], ["d", "a", "b"])
        self.assertEqual(state, original)
        state["retrieved_value_infos"] = [
            ValueInfo(str(i), str(i), "t.region") for i in range(5)
        ]
        self.assertEqual(
            prompt_tables(state)[0]["columns"][2]["examples"],
            [str(i) for i in range(5)],
        )

    async def test_thinking_override_only_applies_to_configured_stages(self):
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import PromptTemplate

        from app.agent.observability import invoke_model
        from app.conf.app_config import app_config

        seen = []

        async def respond(_, **kwargs):
            seen.append(kwargs)
            return "ok"

        with patch.object(
            app_config.llm,
            "stage_enable_thinking",
            {"prepare_query": False, "select_context": False},
        ):
            for stage in (
                "prepare_query",
                "select_context",
                "generate_sql",
                "correct_sql",
            ):
                await invoke_model(
                    PromptTemplate.from_template("test"),
                    RunnableLambda(respond),
                    StrOutputParser(),
                    {},
                    stage=stage,
                )
        self.assertEqual(
            seen,
            [
                {"extra_body": {"enable_thinking": False}},
                {"extra_body": {"enable_thinking": False}},
                {},
                {},
            ],
        )

    async def test_key_columns_use_orm_json_values(self):
        from app.models.column_info import ColumnInfoMySQL
        from app.repositories.mysql.meta.meta_mysql_repository import (
            MetaMySQLRepository,
        )

        column = ColumnInfoMySQL(
            id="t.id",
            name="id",
            type="int",
            role="primary_key",
            examples=[1, 2],
            alias=["编号"],
            description="",
            table_id="t",
        )
        result = types.SimpleNamespace(
            scalars=lambda: types.SimpleNamespace(all=lambda: [column])
        )
        session = types.SimpleNamespace(execute=AsyncMock(return_value=result))
        values = await MetaMySQLRepository(session).get_key_columns_by_table_id("t")
        self.assertEqual(values[0].examples, [1, 2])
        self.assertEqual(values[0].alias, ["编号"])
        self.assertIn("column_info", str(session.execute.await_args.args[0]))

    async def test_metric_vectors_have_stable_ids_when_definition_changes(self):
        from app.services.meta_knowledge_service import MetaKnowledgeService

        repository = types.SimpleNamespace(
            ensure_collection=AsyncMock(), replace_metric_points=AsyncMock()
        )
        service = MetaKnowledgeService(
            None, None, None, self.context["embedding_client"], None, repository
        )
        metric = MetricInfo(
            "AOV", "AOV", "old description", ["fact.amount"], ["平均订单金额"]
        )
        await service._save_metrics_to_qdrant([metric])
        first_ids = repository.replace_metric_points.await_args.args[1]
        metric.description = "new description"
        metric.relevant_columns = ["fact.amount", "fact.id"]
        await service._save_metrics_to_qdrant([metric])
        second = repository.replace_metric_points.await_args.args
        self.assertEqual(first_ids, second[1])
        self.assertTrue(
            all(
                payload["relevant_columns"] == ["fact.amount", "fact.id"]
                for payload in second[3]
            )
        )

    async def test_metric_replacement_deletes_only_stale_points(self):
        from app.repositories.qdrant.metric_qdrant_repository import (
            MetricQdrantRepository,
        )

        client = types.SimpleNamespace(
            scroll=AsyncMock(
                return_value=(
                    [types.SimpleNamespace(id="old"), types.SimpleNamespace(id="keep")],
                    None,
                )
            ),
            delete=AsyncMock(),
        )
        repository = MetricQdrantRepository(client)
        with patch.object(repository, "upsert", new_callable=AsyncMock) as upsert:
            await repository.replace_metric_points(
                "AOV", ["keep"], [[0.1]], [{"id": "AOV"}]
            )
            upsert.assert_awaited_once()
        self.assertEqual(
            client.delete.await_args.kwargs["points_selector"].points, ["old"]
        )
        self.assertEqual(
            client.scroll.await_args.kwargs["scroll_filter"].must[0].match.value, "AOV"
        )

    async def test_service_marks_empty_result_success_before_client_closes(self):
        service_module = importlib.import_module("app.services.query_service")
        from app.core.log import logger

        class FakeGraph:
            async def astream(self, **kwargs):
                yield "custom", {"type": "result", "data": []}

        service = service_module.QueryService(None, None, None, None, None, None)
        messages = []
        sink = logger.add(lambda message: messages.append(str(message)))
        try:
            with patch.object(service_module, "graph", FakeGraph()):
                stream = service.query("empty")
                chunk = await anext(stream)
                self.assertEqual(
                    json.loads(chunk.removeprefix("data: ")),
                    {"type": "result", "data": []},
                )
                await stream.aclose()
        finally:
            logger.remove(sink)
        self.assertTrue(any("Query status=success" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
