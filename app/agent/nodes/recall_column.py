"""
字段召回节点

负责根据关键词从字段向量知识库中召回候选字段
解决问题可能对应哪些数据库字段的问题
共享向量 -> Qdrant 相似度检索 -> ColumnInfo 去重
"""

from time import perf_counter

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.retrieval import SEARCH_CONCURRENCY, bounded_map
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """召回和用户问题语义相关的字段元数据"""

    started = perf_counter()
    writer = runtime.stream_writer
    step = "召回字段信息"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        keywords = list(dict.fromkeys(state["column_terms"]))
        column_qdrant_repository = runtime.context["column_qdrant_repository"]

        # 用字段 id 做唯一键，因为多个关键词、同一字段的多个向量点都可能命中同一个字段
        column_info_map: dict[str, ColumnInfo] = {}

        async def search(keyword):
            return await column_qdrant_repository.search(
                state["term_embeddings"][keyword]
            )

        batches = await bounded_map(keywords, search)
        for batch in batches:
            for item in batch:
                column_info_map.setdefault(item.id, item)

        # 写回 state 的是去重后的 ColumnInfo 列表，不暴露 Qdrant 原始 point 结构
        retrieved_column_infos: list[ColumnInfo] = list(column_info_map.values())

        logger.info(
            "Retrieval branch=column elapsed_ms={:.1f} requests={} candidates={} concurrency={}",
            (perf_counter() - started) * 1000,
            len(keywords),
            len(column_info_map),
            SEARCH_CONCURRENCY,
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return {"retrieved_column_infos": retrieved_column_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
