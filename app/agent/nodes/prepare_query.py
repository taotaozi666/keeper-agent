"""一次调用完成查询理解；明确寒暄不调用模型，不改变查询记忆。"""

import json
import unicodedata
from datetime import date
from typing import Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.observability import invoke_model
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


class QueryTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    column_terms: list[str] = Field(max_length=12)
    metric_terms: list[str] = Field(max_length=12)
    value_terms: list[str] = Field(max_length=12)


class QueryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    metrics: list[str] = Field(default_factory=list, max_length=12)
    time_range: str | None = Field(default=None, max_length=300)
    dimensions: list[str] = Field(default_factory=list, max_length=12)
    filters: list[str] = Field(default_factory=list, max_length=24)
    sort: list[str] = Field(default_factory=list, max_length=12)
    limit: int | None = Field(default=None, ge=1)


class PreparedQuery(QueryTerms):
    action: Literal["query", "clarify", "reply"]
    reply_text: str = Field(max_length=2000)
    relation: Literal["independent", "follow_up"] | None
    resolved_query: str | None = Field(max_length=4000)
    query_context: QueryContext | None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "reply":
            if not self.reply_text.strip():
                raise ValueError("直接回复不能为空")
            if any(
                value is not None
                for value in (self.relation, self.resolved_query, self.query_context)
            ):
                raise ValueError("直接回复不能携带查询上下文")
        else:
            if (
                not self.resolved_query
                or not self.resolved_query.strip()
                or self.query_context is None
                or self.relation is None
            ):
                raise ValueError("查询和澄清必须提供完整的已知条件及问题")
            if self.action == "clarify" and not self.reply_text.strip():
                raise ValueError("澄清问题不能为空")
            if self.action == "query" and self.reply_text:
                raise ValueError("查询分支不能同时直接回复")
        if self.action != "query" and any(
            (self.column_terms, self.metric_terms, self.value_terms)
        ):
            raise ValueError("非查询分支不能携带检索词")
        return self


def greeting_reply(query: str) -> str | None:
    """完整匹配白名单，绝不吞掉‘你好，查一下…’和‘好的/继续’。"""
    normalized = (
        "".join(unicodedata.normalize("NFKC", query).split())
        .casefold()
        .rstrip(".!?。！？，,~～…")
    )
    if normalized in {"你好", "您好", "hi", "hello"}:
        return "你好，我是 Keeper 企业数据助手。你可以直接描述想查询的数据，也可以继续刚才的分析。"
    if normalized in {"谢谢", "多谢", "辛苦了"}:
        return "不客气，有需要随时继续提问。"
    if normalized in {"再见", "拜拜"}:
        return "再见，下次有数据问题可以继续找我。"
    return None


def route_after_prepare(state):
    return (
        "__end__"
        if state.get("action") in ("clarify", "reply")
        else ["embed_terms", "recall_value"]
    )


async def prepare_query(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    step = "统一扩展检索词"
    writer({"type": "progress", "step": step, "status": "running"})
    direct_reply = greeting_reply(state["query"])
    if direct_reply is not None:
        logger.info("Query understanding action=reply source=rule model_calls=0")
        writer({"type": "progress", "step": step, "status": "success"})
        writer({"type": "reply", "message": direct_reply})
        return {"action": "reply"}
    memory_enabled = state.get("memory_enabled", False)
    result = {}
    fallback = False
    try:
        parser = PydanticOutputParser(
            pydantic_object=PreparedQuery if memory_enabled else QueryTerms
        )
        template = load_prompt("prepare_query")
        if memory_enabled:
            template = load_prompt("prepare_query_memory")
        prompt = PromptTemplate.from_template(template)
        inputs = {
            "query": state["query"],
            "today": date.today().isoformat(),
            "memory": json.dumps(
                state.get("conversation_context", {}), ensure_ascii=False
            ),
            "format_instructions": parser.get_format_instructions(),
        }
        terms = await invoke_model(prompt, llm, parser, inputs, stage="prepare_query")
        if memory_enabled:
            logger.info("Query understanding action={} source=model", terms.action)
            result = {"action": terms.action}
            if terms.action != "reply":
                result.update(
                    query=terms.resolved_query,
                    query_context=terms.query_context.model_dump(),
                )
            if terms.action != "query":
                writer({"type": "progress", "step": step, "status": "success"})
                writer(
                    {
                        "type": "reply" if terms.action == "reply" else "clarification",
                        "message": terms.reply_text.strip(),
                    }
                )
                return result
    except Exception as exc:
        # 带记忆时禁止把未补全的追问直接交给 SQL 生成。
        if memory_enabled:
            raise ValueError("本次问题理解失败，请补充完整查询条件后重试。") from exc
        fallback = True
        terms = QueryTerms(column_terms=[], metric_terms=[], value_terms=[])
        logger.warning(f"检索词扩展失败，回退到原始关键词：{exc}")
    base_terms = (
        [result.get("query", state["query"])]
        if memory_enabled
        else [*state["keywords"], state["query"]]
    )
    for name in ("column_terms", "metric_terms", "value_terms"):
        result[name] = list(
            dict.fromkeys(
                [*base_terms, *(t.strip() for t in getattr(terms, name) if t.strip())]
            )
        )
    logger.info("Query expansion fallback={} memory={}", fallback, memory_enabled)
    writer({"type": "progress", "step": step, "status": "success"})
    return result
