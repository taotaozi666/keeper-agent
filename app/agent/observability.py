"""模型调用统计：服务端没有返回用量时明确记录 unknown，不估算 Token。"""

import json
from functools import wraps
from time import perf_counter
from uuid import uuid4

from app.conf.app_config import app_config
from app.core.log import logger
from app.core.telemetry import record_metric


def render_content(content) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, default=str)


async def invoke_model(prompt, model, parser, inputs: dict, *, stage: str):
    prompt_value = prompt.invoke(inputs)
    call_id = uuid4().hex[:12]
    log_conversations = app_config.llm.log_conversations
    if log_conversations:
        messages = []
        for index, message in enumerate(prompt_value.to_messages(), start=1):
            messages.append(
                f"--- message {index} [{message.type}] ---\n{render_content(message.content)}"
            )
            if getattr(message, "tool_calls", None):
                messages.append(f"tool_calls: {render_content(message.tool_calls)}")
            if getattr(message, "tool_call_id", None):
                messages.append(f"tool_call_id: {message.tool_call_id}")
            if message.additional_kwargs:
                messages.append(
                    f"additional_kwargs:\n{render_content(message.additional_kwargs)}"
                )
        logger.info(
            "LLM_INPUT stage={} call_id={} BEGIN\n{}\nLLM_INPUT END",
            stage,
            call_id,
            "\n".join(messages),
        )
    started = perf_counter()
    model_name = (
        getattr(model, "model_name", None)
        or getattr(model, "model", None)
        or type(model).__name__
    )
    try:
        options = {}
        thinking = app_config.llm.stage_enable_thinking.get(stage)
        if thinking is not None:
            options["extra_body"] = {"enable_thinking": thinking}
        logger.info(
            "LLM_OPTIONS stage={} call_id={} enable_thinking={}",
            stage,
            call_id,
            thinking if thinking is not None else "provider_default",
        )
        response = await model.ainvoke(prompt_value, **options)
        usage = getattr(response, "usage_metadata", None) or {}
        metadata = getattr(response, "response_metadata", None) or {}
        raw_usage = metadata.get("token_usage") or {}
        content = getattr(response, "content", response)
        if log_conversations:
            additional = getattr(response, "additional_kwargs", None) or {}
            # 仅记录接口明确返回的推理字段，不推测未暴露的内容。
            reasoning = (
                "\n".join(
                    f"{key}:\n{render_content(additional[key])}"
                    for key in ("reasoning_content", "reasoning")
                    if key in additional
                )
                or "(接口未返回单独的推理字段)"
            )
            details = {
                "usage": usage or raw_usage,
                "finish_reason": metadata.get("finish_reason"),
                "tool_calls": getattr(response, "tool_calls", []),
            }
            logger.info(
                "LLM_OUTPUT stage={} call_id={} BEGIN\ncontent:\n{}\nreasoning:\n{}\nmetadata:\n{}\nLLM_OUTPUT END",
                stage,
                call_id,
                render_content(content),
                reasoning,
                render_content(details),
            )
        logger.info(
            "LLM stage={} call_id={} model={} elapsed_ms={:.1f} input_chars={} output_chars={} "
            "input_tokens={} output_tokens={} total_tokens={} reasoning_tokens={}",
            stage,
            call_id,
            metadata.get("model_name") or model_name,
            (perf_counter() - started) * 1000,
            len(prompt_value.to_string()),
            len(str(content)),
            usage.get("input_tokens", raw_usage.get("prompt_tokens", "unknown")),
            usage.get("output_tokens", raw_usage.get("completion_tokens", "unknown")),
            usage.get("total_tokens", raw_usage.get("total_tokens", "unknown")),
            (usage.get("output_token_details") or {}).get(
                "reasoning",
                (raw_usage.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens", "unknown"
                ),
            ),
        )
        record_metric(
            {
                "kind": "llm",
                "stage": stage,
                "call_id": call_id,
                "model": metadata.get("model_name") or model_name,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                "enable_thinking": thinking,
                "input_tokens": usage.get(
                    "input_tokens", raw_usage.get("prompt_tokens")
                ),
                "output_tokens": usage.get(
                    "output_tokens", raw_usage.get("completion_tokens")
                ),
                "total_tokens": usage.get(
                    "total_tokens", raw_usage.get("total_tokens")
                ),
                "reasoning_tokens": (usage.get("output_token_details") or {}).get(
                    "reasoning",
                    (raw_usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    ),
                ),
            }
        )
        return await parser.ainvoke(response)
    except Exception:
        logger.error(
            "LLM stage={} call_id={} model={} failed elapsed_ms={:.1f}",
            stage,
            call_id,
            model_name,
            (perf_counter() - started) * 1000,
        )
        raise


def context_counts(state: dict) -> dict:
    tables = state["table_infos"]
    return {
        "tables": len(tables),
        "columns": sum(len(table["columns"]) for table in tables),
        "metrics": len(state["metric_infos"]),
    }


def timed_node(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        started = perf_counter()
        status = "failed"
        try:
            result = await function(*args, **kwargs)
            status = "completed"
            return result
        finally:
            record_metric(
                {
                    "kind": "node",
                    "node": function.__name__,
                    "status": status,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                }
            )
            logger.info(
                "Node name={} status={} elapsed_ms={:.1f}",
                function.__name__,
                status,
                (perf_counter() - started) * 1000,
            )

    return wrapped
