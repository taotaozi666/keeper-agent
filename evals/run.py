"""批量问数评测入口：python -m evals.run --help。"""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.core.telemetry import metrics_context
from evals.comparison import compare_results

DEFAULT_DATASET = Path(__file__).with_name("core_queries.json")


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def load_dataset(path: Path) -> dict:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    cases = dataset.get("cases", [])
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("测试集为空或题目 ID 重复")
    for case in cases:
        if case.get("expected_action") != "execute":
            raise ValueError(f"{case['id']}：当前运行器仅支持 execute 类型")
        if not case.get("question") or not case.get("reference_sql"):
            raise ValueError(f"{case['id']}：缺少问题或参考 SQL")
        if not isinstance(case.get("expected_result"), list) or not isinstance(
            case.get("expected_columns"), list
        ):
            raise ValueError(f"{case['id']}：缺少预期结果或列名")
        if any(
            set(row) != set(case["expected_columns"]) for row in case["expected_result"]
        ):
            raise ValueError(f"{case['id']}：预期结果列名不一致")
        tolerance = float(
            case.get("comparison", {}).get("numeric_absolute_tolerance", 0)
        )
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError(f"{case['id']}：数值容差无效")
    return dataset


async def evaluate_case(case, executor, *, timeout: float, reference_only=False):
    started = perf_counter()
    metrics = []
    token = metrics_context.set(metrics)
    record = {
        "id": case["id"],
        "question": case["question"],
        "started_at": now(),
        "expected_result": case["expected_result"],
        "expected_columns": case["expected_columns"],
        "reference_sql": case["reference_sql"],
        "sql_history": [],
        "actual_result": None,
        "events": [],
        "metrics": metrics,
    }
    try:
        async with asyncio.timeout(timeout):
            await executor(case, record)
        if record["actual_result"] is None:
            raise ValueError("工作流未返回 result 事件")
        comparison = compare_results(case, record["actual_result"])
        record["comparison"] = comparison
        record["status"] = "failed"
        if comparison["match"]:
            record["status"] = (
                "needs_review"
                if comparison.get("needs_review") and not reference_only
                else "passed"
            )
    except TimeoutError:
        record.update(status="timeout", error=f"超过单题 {timeout:g} 秒限制")
    except Exception as exc:
        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        record.update(
            finished_at=now(), elapsed_ms=round((perf_counter() - started) * 1000, 2)
        )
        metrics_context.reset(token)
    return record


def summarize(records):
    counts = {
        status: sum(record["status"] == status for record in records)
        for status in ("passed", "failed", "error", "timeout", "needs_review")
    }
    durations = sorted(record["elapsed_ms"] for record in records)
    calls = [
        metric
        for record in records
        for metric in record["metrics"]
        if metric["kind"] == "llm"
    ]
    return {
        "total": len(records),
        **counts,
        "pass_rate": round(counts["passed"] / len(records), 4) if records else None,
        "mean_elapsed_ms": round(statistics.mean(durations), 2) if durations else None,
        "median_elapsed_ms": round(statistics.median(durations), 2)
        if durations
        else None,
        "p95_elapsed_ms": durations[max(0, math.ceil(len(durations) * 0.95) - 1)]
        if durations
        else None,
        "model_responses": len(calls),
        "known_total_tokens": sum(call.get("total_tokens") or 0 for call in calls),
        "responses_without_token_usage": sum(
            call.get("total_tokens") is None for call in calls
        ),
    }


def save_reports(directory: Path, report: dict):
    temporary = directory / "report.json.tmp"
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(directory / "report.json")
    summary = report["summary"]
    lines = [
        "# Keeper 批量评测报告",
        "",
        f"模式：{report['mode']}；开始：{report['started_at']}；状态：{report['status']}。",
        "",
        f"完成 {summary['total']} / {report['planned']} 题；通过 {summary['passed']}；不一致 {summary['failed']}；异常 {summary['error']}；超时 {summary['timeout']}；待人工确认 {summary['needs_review']}。",
        "",
        f"平均耗时：{summary['mean_elapsed_ms']} ms；中位数：{summary['median_elapsed_ms']} ms；P95：{summary['p95_elapsed_ms']} ms。",
        "",
        "列名默认严格匹配；可在题目中用 column_aliases 显式映射。空结果不会直接记为 Agent 通过。reference_only 模式只核验参考答案，不代表 Agent 表现。",
        "",
        "| ID | 状态 | 耗时（秒） | 问题 | 说明 |",
        "| --- | --- | ---: | --- | --- |",
    ]

    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    for record in report["cases"]:
        reason = record.get("error") or record.get("comparison", {}).get("reason", "")
        lines.append(
            f"| {record['id']} | {record['status']} | {record['elapsed_ms'] / 1000:.2f} | {clean(record['question'])} | {clean(reason)} |"
        )
    lines.extend(
        [
            "",
            "每题实际数据、参考数据、SQL 历史、进度事件、节点和模型耗时见同目录 report.json；results.jsonl 每完成一题立即追加保存。",
            "",
        ]
    )
    for record in report["cases"]:
        lines.extend(
            [
                "<details>",
                f"<summary>{clean(record['id'])} · {record['status']} · 实际结果与 SQL</summary>",
                "",
                "```json",
                json.dumps(
                    {
                        "expected": record["expected_result"],
                        "actual": record["actual_result"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=json_default,
                ),
                "```",
                "",
            ]
        )
        for item in record["sql_history"]:
            lines.extend(
                [f"节点：{item['node']}", "", "```sql", item["sql"], "```", ""]
            )
        lines.extend(["</details>", ""])
    temporary = directory / "report.md.tmp"
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(directory / "report.md")


async def verify_snapshot(session, dataset):
    from sqlalchemy import text

    expected = dataset.get("snapshot", {}).get("data_sha256")
    if not expected:
        return
    fingerprint = hashlib.sha256()
    for table, key in (
        ("dim_region", "region_id"),
        ("dim_customer", "customer_id"),
        ("dim_product", "product_id"),
        ("dim_date", "date_id"),
        ("fact_order", "order_id"),
    ):
        rows = [
            dict(row)
            for row in (
                await session.execute(text(f"SELECT * FROM {table} ORDER BY {key}"))
            ).mappings()
        ]
        fingerprint.update(
            json.dumps(
                {"table": table, "rows": rows},
                ensure_ascii=False,
                sort_keys=True,
                default=json_default,
            ).encode("utf-8")
        )
    if fingerprint.hexdigest() != expected:
        raise ValueError(
            "数据库与参考答案快照不一致，请核对数据后重新生成答案；本题未调用模型"
        )


async def collect_graph_events(graph, question, context, record):
    async for mode, chunk in graph.astream(
        {"query": question}, context=context, stream_mode=["custom", "updates"]
    ):
        if mode == "custom":
            record["events"].append(chunk)
            if chunk.get("type") == "result":
                record["actual_result"] = chunk["data"]
        else:
            for node, update in chunk.items():
                if isinstance(update, dict) and "sql" in update:
                    record["sql_history"].append({"node": node, "sql": update["sql"]})


async def run(args, dataset, cases, directory):
    from sqlalchemy import text

    from app.clients.mysql_client_manager import (
        dw_mysql_client_manager,
        meta_mysql_client_manager,
    )
    from app.conf.app_config import app_config
    from app.core.context import request_id_ctx_var
    from app.core.log import logger

    # 初始化日志与客户端发生在独立 CLI 进程，不影响正在运行的 FastAPI。
    logger.remove()
    logger.add(directory / "agent.log", level="INFO", encoding="utf-8")
    app_config.llm.log_conversations = args.log_conversations
    dw_mysql_client_manager.init()
    managers = [dw_mysql_client_manager]
    if not args.reference_only:
        from app.agent.graph import graph
        from app.clients.embedding_client_manager import embedding_client_manager
        from app.clients.es_client_manager import es_client_manager
        from app.clients.qdrant_client_manager import qdrant_client_manager
        from app.repositories.es.value_es_repository import ValueESRepository
        from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
        from app.repositories.mysql.meta.meta_mysql_repository import (
            MetaMySQLRepository,
        )
        from app.repositories.qdrant.column_qdrant_repository import (
            ColumnQdrantRepository,
        )
        from app.repositories.qdrant.metric_qdrant_repository import (
            MetricQdrantRepository,
        )

        for manager in (
            meta_mysql_client_manager,
            es_client_manager,
            qdrant_client_manager,
        ):
            manager.init()
            managers.append(manager)
        embedding_client_manager.init()

    async def executor(case, record):
        request_token = request_id_ctx_var.set(f"eval-{directory.name}-{case['id']}")
        try:
            async with dw_mysql_client_manager.session_factory() as dw:
                await dw.execute(
                    text("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                )
                await verify_snapshot(dw, dataset)
                if args.reference_only:
                    result = await dw.execute(text(case["reference_sql"]))
                    record["actual_result"] = [dict(row) for row in result.mappings()]
                    record["sql_history"].append(
                        {"node": "reference", "sql": case["reference_sql"]}
                    )
                    return
                async with meta_mysql_client_manager.session_factory() as meta:
                    context = dict(
                        meta_mysql_repository=MetaMySQLRepository(meta),
                        dw_mysql_repository=DWMySQLRepository(dw),
                        column_qdrant_repository=ColumnQdrantRepository(
                            qdrant_client_manager.client
                        ),
                        metric_qdrant_repository=MetricQdrantRepository(
                            qdrant_client_manager.client
                        ),
                        value_es_repository=ValueESRepository(es_client_manager.client),
                        embedding_client=embedding_client_manager.client,
                    )
                    await collect_graph_events(graph, case["question"], context, record)
        finally:
            request_id_ctx_var.reset(request_token)

    report = {
        "mode": "reference_only" if args.reference_only else "agent",
        "started_at": now(),
        "status": "running",
        "planned": len(cases),
        "dataset": str(args.dataset.resolve()),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "snapshot": dataset.get("snapshot"),
        "model": app_config.llm.model_name,
        "stage_enable_thinking": app_config.llm.stage_enable_thinking,
        "cases": [],
        "summary": summarize([]),
    }
    save_reports(directory, report)
    try:
        with (directory / "results.jsonl").open("a", encoding="utf-8") as journal:
            for index, case in enumerate(cases, 1):
                print(
                    f"[{index}/{len(cases)}] {case['id']} {case['question']}",
                    flush=True,
                )
                record = await evaluate_case(
                    case,
                    executor,
                    timeout=args.timeout,
                    reference_only=args.reference_only,
                )
                report["cases"].append(record)
                report["summary"] = summarize(report["cases"])
                journal.write(
                    json.dumps(record, ensure_ascii=False, default=json_default) + "\n"
                )
                journal.flush()
                save_reports(directory, report)
                print(
                    f"  {record['status']} {record['elapsed_ms'] / 1000:.2f}s",
                    flush=True,
                )
        report["status"] = "completed"
    finally:
        report["finished_at"] = now()
        if report["status"] == "running":
            report["status"] = "interrupted"
        save_reports(directory, report)
        for manager in reversed(managers):
            await manager.close()
    print("Report:", directory / "report.md")
    return (
        1
        if any(
            report["summary"][key]
            for key in ("failed", "error", "timeout", "needs_review")
        )
        else 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+", help="例如 keeper_001 keeper_007")
    parser.add_argument("--timeout", type=float, default=90, help="每题总超时秒数")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("reports")
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只验证测试集，不连接服务、不调用模型"
    )
    parser.add_argument(
        "--reference-only", action="store_true", help="只核验数据库参考答案，不调用模型"
    )
    parser.add_argument(
        "--log-conversations",
        action="store_true",
        help="将完整模型对话记录到本轮 agent.log",
    )
    args = parser.parse_args()
    if (
        args.timeout <= 0
        or not math.isfinite(args.timeout)
        or (args.limit is not None and args.limit <= 0)
    ):
        parser.error("timeout 和 limit 必须是正数")
    dataset = load_dataset(args.dataset)
    cases = dataset["cases"]
    if args.ids:
        unknown = set(args.ids) - {case["id"] for case in cases}
        if unknown:
            parser.error(f"未知题目 ID：{sorted(unknown)}")
        cases = [case for case in cases if case["id"] in args.ids]
    if args.limit:
        cases = cases[: args.limit]
    if args.dry_run:
        print(f"Validated {len(cases)} cases; no database or model calls.")
        return 0
    directory = args.output / (
        datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid4().hex[:6]
    )
    directory.mkdir(parents=True, exist_ok=False)
    return asyncio.run(run(args, dataset, cases, directory))


if __name__ == "__main__":
    raise SystemExit(main())
