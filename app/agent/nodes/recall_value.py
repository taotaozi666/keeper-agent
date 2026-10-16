"""
字段取值召回节点

负责从字段值全文索引中召回候选取值
当用户问题里出现店铺名 类目名 地区名等业务值时，这一步可以帮助定位真实字段和值
实现路径和字段/指标召回不同，统一扩展词 -> Elasticsearch 全文检索 -> ValueInfo 去重
"""

from time import perf_counter

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.retrieval import SEARCH_CONCURRENCY, bounded_map
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """召回和用户问题相关的字段取值"""

    started = perf_counter()
    writer = runtime.stream_writer
    step = "召回字段取值"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        keywords = list(dict.fromkeys(state["value_terms"]))
        value_es_repository = runtime.context["value_es_repository"]

        # 用 ValueInfo.id 去重，避免多个关键词命中同一条字段值记录
        value_infos_map: dict[str, ValueInfo] = {}
        batches = await bounded_map(keywords, value_es_repository.search)
        for batch in batches:
            for item in batch:
                value_infos_map.setdefault(item.id, item)

        # 写回 state 的是去重后的字段值实体，后续合并节点再决定如何组织上下文
        retrieved_value_infos: list[ValueInfo] = list(value_infos_map.values())
        logger.info(
            "Retrieval branch=value elapsed_ms={:.1f} requests={} candidates={} concurrency={}",
            (perf_counter() - started) * 1000,
            len(keywords),
            len(value_infos_map),
            SEARCH_CONCURRENCY,
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return {"retrieved_value_infos": retrieved_value_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
