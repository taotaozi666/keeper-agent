"""一次模型调用联合选择表字段和指标，并由程序保证依赖完整。"""

from copy import deepcopy

import yaml
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.observability import context_counts, invoke_model
from app.agent.prompt_context import prompt_tables
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tables: dict[str, list[str]]
    metrics: list[str]


def apply_selection(state: DataAgentState, selection: ContextSelection) -> dict:
    """只选取已知实体；补回指标依赖及所保留表的主外键，不修改输入。"""
    tables = {table["name"]: table for table in state["table_infos"]}
    metrics = {metric["name"]: metric for metric in state["metric_infos"]}
    for name, columns in selection.tables.items():
        if name not in tables:
            raise ValueError(f"未知候选表：{name}")
        known = {column["name"] for column in tables[name]["columns"]}
        if set(columns) - known:
            raise ValueError(f"表 {name} 包含未知候选字段")
    if set(selection.metrics) - metrics.keys():
        raise ValueError("筛选结果包含未知指标")

    selected = {name: set(columns) for name, columns in selection.tables.items()}
    selected_metrics = [
        metric for name, metric in metrics.items() if name in selection.metrics
    ]
    for metric in selected_metrics:
        for column_id in metric["relevant_columns"]:
            table_name, column_name = column_id.rsplit(".", 1)
            table = tables.get(table_name)
            if table is None or not any(
                c["name"] == column_name for c in table["columns"]
            ):
                raise ValueError(f"指标依赖不在候选上下文中：{column_id}")
            selected.setdefault(table_name, set()).add(column_name)

    filtered = []
    for name, table in tables.items():
        if name not in selected:
            continue
        columns = [
            column
            for column in table["columns"]
            if (
                column["name"] in selected[name]
                or column["role"] in ("primary_key", "foreign_key")
            )
        ]
        if not columns:
            raise ValueError(f"表 {name} 没有可用字段")
        filtered.append({**deepcopy(table), "columns": deepcopy(columns)})
    if not filtered:
        raise ValueError("未选择任何可查询的表")
    return {"table_infos": filtered, "metric_infos": deepcopy(selected_metrics)}


async def select_context(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    step = "联合筛选表字段与指标"
    writer({"type": "progress", "step": step, "status": "running"})
    try:
        if not state["table_infos"]:
            raise ValueError("未召回可用表结构，无法生成 SQL")
        prompt = PromptTemplate.from_template(load_prompt("select_context"))
        parser = PydanticOutputParser(pydantic_object=ContextSelection)
        selection = await invoke_model(
            prompt,
            llm,
            parser,
            {
                "query": state["query"],
                "table_infos": yaml.safe_dump(
                    prompt_tables(state), allow_unicode=True, sort_keys=False
                ),
                "metric_infos": yaml.safe_dump(
                    state["metric_infos"], allow_unicode=True, sort_keys=False
                ),
            },
            stage="select_context",
        )
        result = apply_selection(state, selection)
        logger.info(
            "Context selection before={} after={} selected_tables={} selected_metrics={}",
            context_counts(state),
            context_counts(result),
            [t["name"] for t in result["table_infos"]],
            [m["name"] for m in result["metric_infos"]],
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return result
    except Exception as exc:
        logger.error(f"{step} failed: {exc}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
