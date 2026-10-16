"""
指标召回节点

负责根据用户问题从指标向量知识库中召回候选指标
帮助 Agent 把“销售额 转化率 客单价”等业务表达映射到已定义指标
共享向量 -> Qdrant 相似度检索 -> MetricInfo 去重
"""

from time import perf_counter

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.retrieval import SEARCH_CONCURRENCY, bounded_map
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo


async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """召回和用户问题语义相关的业务指标"""

    started = perf_counter()
    writer = runtime.stream_writer
    step = "召回指标信息"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        keywords = list(dict.fromkeys(state["metric_terms"]))
        metric_qdrant_repository = runtime.context["metric_qdrant_repository"]

        # 用指标 id 做唯一键，避免多个关键词命中同一个指标时重复写入 state
        metric_info_map: dict[str, MetricInfo] = {}

        async def search(keyword):
            return await metric_qdrant_repository.search(
                state["term_embeddings"][keyword]
            )

        batches = await bounded_map(keywords, search)
        for batch in batches:
            for item in batch:
                metric_info_map.setdefault(item.id, item)

        # 写回 state 的是业务实体列表，后续过滤节点不需要关心 Qdrant 原始 point 结构
        retrieved_metric_infos: list[MetricInfo] = list(metric_info_map.values())
        logger.info(
            "Retrieval branch=metric elapsed_ms={:.1f} requests={} candidates={} concurrency={}",
            (perf_counter() - started) * 1000,
            len(keywords),
            len(metric_info_map),
            SEARCH_CONCURRENCY,
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return {"retrieved_metric_infos": retrieved_metric_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
