"""离线验证工具循环与真实文件编码，不访问模型。"""

import io
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree
from zipfile import ZipFile

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.tool_agent import run_tool_agent
from app.repositories.mysql.dw.dw_mysql_repository import ensure_read_query
from app.repositories.mysql.meta.conversation_repository import snapshot
from app.services.artifact_service import export_bytes
from test import test_agent_workflow  # noqa: F401

RID = "0992fc84-17d9-4539-b4f4-6db48e03ff82"


def call(name, args):
    return AIMessage(
        content="", tool_calls=[{"id": "call1", "name": name, "args": args}]
    )


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        artifact = SimpleNamespace(
            id=RID,
            name="结果.xlsx",
            kind="xlsx",
            size=500,
            row_count=30,
            expires_at=datetime(2030, 1, 1),
        )
        artifacts = SimpleNamespace(
            recent_results=AsyncMock(return_value=[]),
            save_result=AsyncMock(return_value=artifact),
            export=AsyncMock(return_value=artifact),
        )

        async def events(state):
            state["sql"] = "SELECT 1"
            yield {"type": "result", "data": [{"金额": i} for i in range(30)]}

        return SimpleNamespace(
            artifact_service=artifacts,
            _events=events,
            dw_mysql_repository=SimpleNamespace(),
        )

    async def test_query_export_final_and_model_feedback(self):
        service = self.service()
        model = SimpleNamespace(bind_tools=lambda *a, **k: object())
        answers = [
            call("query_data", {"query": "查询金额"}),
            call("export_query_result", {"query_result_id": RID, "format": "xlsx"}),
            AIMessage(content="已导出。"),
        ]
        state = {"query": "查询并导出"}
        with patch(
            "app.agent.tool_agent.invoke_model", AsyncMock(side_effect=answers)
        ) as invoke:
            events = [
                e async for e in run_tool_agent(service, state, "c", "t", model=model)
            ]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len(events[-1]["files"]), 1)
        self.assertEqual(len(events[-1]["results"][0]["data"]), 30)
        self.assertFalse(next(e for e in events if e["type"] == "result")["terminal"])
        messages = invoke.call_args.args[3]["messages"]
        feedback = json.loads(
            next(m.content for m in messages if isinstance(m, ToolMessage))
        )
        self.assertTrue(feedback["preview_truncated"])
        self.assertEqual(len(feedback["preview"]), 20)
        service.artifact_service.export.assert_awaited_once_with("c", "t", RID, "xlsx")
        self.assertEqual(state["last_query"]["query_result_id"], RID)

    async def test_failed_tool_is_not_success_and_duplicate_stops(self):
        model = SimpleNamespace(bind_tools=lambda *a, **k: object())
        bad = call("export_query_result", {"query_result_id": "fake", "format": "xlsx"})
        for answers in ([bad, AIMessage(content="无法导出")], [bad, bad]):
            with patch(
                "app.agent.tool_agent.invoke_model", AsyncMock(side_effect=answers)
            ):
                if answers[-1] is bad:
                    with self.assertRaisesRegex(ValueError, "重复"):
                        [
                            e
                            async for e in run_tool_agent(
                                self.service(), {"query": "导出"}, "c", "t", model=model
                            )
                        ]
                else:
                    events = [
                        e
                        async for e in run_tool_agent(
                            self.service(), {"query": "导出"}, "c", "t", model=model
                        )
                    ]
                    self.assertIn("error", events[-1])

    async def test_greeting_without_model(self):
        events = [
            e
            async for e in run_tool_agent(
                self.service(), {"query": "你好"}, "c", "t", model=object()
            )
        ]
        self.assertEqual(events[0]["type"], "reply")

    async def test_call_limit_and_clarification(self):
        model = SimpleNamespace(bind_tools=lambda *a, **k: object())
        answer = call("query_data", {"query": "查询金额"})
        with patch("app.agent.tool_agent.invoke_model", AsyncMock(return_value=answer)):
            with self.assertRaisesRegex(ValueError, "上限"):
                [
                    e
                    async for e in run_tool_agent(
                        self.service(),
                        {"query": "查询"},
                        "c",
                        "t",
                        model=model,
                        max_calls=1,
                    )
                ]
        service = self.service()

        async def clarify(state):
            yield {"type": "clarification", "message": "哪一年？"}

        service._events = clarify
        state = {"query": "查询"}
        with patch("app.agent.tool_agent.invoke_model", AsyncMock(return_value=answer)):
            events = [
                e async for e in run_tool_agent(service, state, "c", "t", model=model)
            ]
        self.assertTrue(events[-1]["clarification"])
        self.assertEqual(state["pending_query"]["message"], "哪一年？")
        service.artifact_service.save_result.assert_not_awaited()


class ExportTests(unittest.TestCase):
    def test_csv_and_xlsx(self):
        rows = [{"名称": "=1+1", "金额": 12.5, "备注": "<测试>&"}]
        csv = export_bytes(rows, "csv").decode("utf-8-sig")
        self.assertIn("'=1+1", csv)
        with ZipFile(io.BytesIO(export_bytes(rows, "xlsx"))) as archive:
            for name in archive.namelist():
                ElementTree.fromstring(archive.read(name))
            xml = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertNotIn("<f>", xml)
            self.assertIn("<v>12.5</v>", xml)
            self.assertIn("&lt;测试&gt;&amp;", xml)

    def test_snapshot_preserves_files_but_limits_rows(self):
        saved = snapshot(
            {
                "type": "done",
                "results": [
                    {"query_result_id": RID, "data": [{"a": i} for i in range(150)]}
                ],
                "files": [{"id": RID}],
            }
        )
        self.assertEqual(len(saved["results"][0]["data"]), 100)
        self.assertTrue(saved["results"][0]["truncated"])
        self.assertEqual(saved["files"], [{"id": RID}])

    def test_sql_guards(self):
        for sql in [
            "SELECT 1",
            "WITH a AS (SELECT 1) SELECT * FROM a",
            "SELECT 'DROP table; --' AS `update`",
        ]:
            ensure_read_query(sql)
        for sql in [
            "DELETE FROM a",
            "SELECT 1; DROP TABLE a",
            "SELECT 1 INTO OUTFILE '/tmp/a'",
            "SELECT SLEEP(30)",
            "SELECT /*!50000 1 */",
        ]:
            with self.assertRaises(ValueError):
                ensure_read_query(sql)
