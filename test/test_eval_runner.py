"""评测运行器离线测试，不需要配置、数据库或模型。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.core.telemetry import record_metric
from evals.comparison import compare_results
from evals.run import (
    DEFAULT_DATASET,
    evaluate_case,
    load_dataset,
    save_reports,
    summarize,
)


def example(rows=None, *, ordered=False):
    return {
        "id": "test_001",
        "question": "测试",
        "expected_action": "execute",
        "reference_sql": "SELECT 1 AS value",
        "expected_columns": ["value"],
        "expected_result": rows if rows is not None else [{"value": 1}],
        "comparison": {"order_sensitive": ordered, "numeric_absolute_tolerance": 0.01},
    }


class ComparisonTests(unittest.TestCase):
    def test_existing_dataset_has_twenty_valid_cases(self):
        self.assertEqual(len(load_dataset(DEFAULT_DATASET)["cases"]), 20)

    def test_numeric_tolerance_and_null(self):
        self.assertTrue(compare_results(example(), [{"value": 1.005}])["match"])
        self.assertFalse(compare_results(example(), [{"value": 1.02}])["match"])
        self.assertFalse(compare_results(example(), [{"value": "1"}])["match"])
        self.assertFalse(compare_results(example(), [{"value": True}])["match"])
        self.assertTrue(
            compare_results(example([{"value": None}]), [{"value": None}])["match"]
        )
        self.assertFalse(compare_results(example(), [{"value": None}])["match"])

    def test_row_order_and_duplicate_counts(self):
        case = example([{"value": 1}, {"value": 2}])
        self.assertTrue(compare_results(case, [{"value": 2}, {"value": 1}])["match"])
        case["comparison"]["order_sensitive"] = True
        self.assertFalse(compare_results(case, [{"value": 2}, {"value": 1}])["match"])
        self.assertFalse(
            compare_results(
                example([{"value": 1}, {"value": 1}]), [{"value": 1}, {"value": 2}]
            )["match"]
        )

    def test_tolerance_matching_is_not_greedy(self):
        case = example([{"value": 1.00}, {"value": 1.02}])
        self.assertTrue(
            compare_results(case, [{"value": 1.01}, {"value": 0.99}])["match"]
        )

    def test_explicit_column_aliases(self):
        case = example()
        self.assertFalse(compare_results(case, [{"alias": 1}])["match"])
        case["column_aliases"] = {"alias": "value"}
        self.assertTrue(compare_results(case, [{"alias": 1}])["match"])
        self.assertFalse(compare_results(case, [{"alias": 1, "value": 1}])["match"])

    def test_empty_results_require_review(self):
        result = compare_results(example([]), [])
        self.assertTrue(result["match"])
        self.assertTrue(result["needs_review"])

    def test_invalid_dataset_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(
                json.dumps({"cases": [example(), example()]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "ID 重复"):
                load_dataset(path)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_stream_captures_sql_repairs_and_result(self):
        from evals.run import collect_graph_events

        class FakeGraph:
            async def astream(self, state, *, context, stream_mode):
                yield "updates", {"generate_sql": {"sql": "SELECT broken"}}
                yield (
                    "custom",
                    {"type": "progress", "step": "校正SQL", "status": "running"},
                )
                yield "updates", {"correct_sql": {"sql": "SELECT 1 AS value"}}
                yield "custom", {"type": "result", "data": [{"value": 1}]}

        async def execute(case, record):
            await collect_graph_events(FakeGraph(), case["question"], {}, record)

        record = await evaluate_case(example(), execute, timeout=1)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(
            [item["node"] for item in record["sql_history"]],
            ["generate_sql", "correct_sql"],
        )
        self.assertEqual(record["events"][0]["step"], "校正SQL")

    async def test_execution_records_results_timing_and_metrics(self):
        async def execute(case, record):
            record_metric({"kind": "llm", "total_tokens": 10})
            record["actual_result"] = [{"value": 1}]
            record["sql_history"].append({"node": "generate_sql", "sql": "SELECT 1"})

        result = await evaluate_case(example(), execute, timeout=1)
        self.assertEqual(result["status"], "passed")
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertEqual(len(result["metrics"]), 1)
        self.assertTrue(result["started_at"].endswith("+08:00"))
        self.assertEqual(summarize([result])["known_total_tokens"], 10)

    async def test_error_does_not_prevent_next_case(self):
        async def fail(case, record):
            raise ValueError("broken")

        async def succeed(case, record):
            record["actual_result"] = [{"value": 1}]

        failed = await evaluate_case(example(), fail, timeout=1)
        passed = await evaluate_case(example(), succeed, timeout=1)
        self.assertEqual(failed["status"], "error")
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(summarize([failed, passed])["pass_rate"], 0.5)

    async def test_timeout_and_missing_result(self):
        async def wait(case, record):
            await asyncio.sleep(5)

        async def no_result(case, record):
            pass

        self.assertEqual(
            (await evaluate_case(example(), wait, timeout=0.01))["status"], "timeout"
        )
        self.assertEqual(
            (await evaluate_case(example(), no_result, timeout=1))["status"], "error"
        )

    async def test_empty_agent_answer_is_not_auto_passed(self):
        async def execute(case, record):
            record["actual_result"] = []

        result = await evaluate_case(example([]), execute, timeout=1)
        self.assertEqual(result["status"], "needs_review")
        reference = await evaluate_case(
            example([]), execute, timeout=1, reference_only=True
        )
        self.assertEqual(reference["status"], "passed")

    async def test_report_files_are_written(self):
        async def execute(case, record):
            record["actual_result"] = [{"value": 1}]

        result = await evaluate_case(example(), execute, timeout=1)
        report = {
            "mode": "agent",
            "started_at": result["started_at"],
            "status": "completed",
            "planned": 1,
            "cases": [result],
            "summary": summarize([result]),
        }
        with tempfile.TemporaryDirectory() as directory:
            save_reports(Path(directory), report)
            saved = json.loads(
                (Path(directory) / "report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["cases"][0]["actual_result"], [{"value": 1}])
            self.assertIn(
                "test_001", (Path(directory) / "report.md").read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    unittest.main()
