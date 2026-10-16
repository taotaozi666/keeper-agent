"""字段与指标检索词统一去重、分批向量化，向量仅在当前请求内复用。"""

from time import perf_counter

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.retrieval import EMBEDDING_BATCH_SIZE
from app.agent.state import DataAgentState
from app.core.log import logger


async def embed_terms(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    step = "批量向量化检索词"
    writer = runtime.stream_writer
    started = perf_counter()
    writer({"type": "progress", "step": step, "status": "running"})
    try:
        all_terms = [*state["column_terms"], *state["metric_terms"]]
        terms = list(dict.fromkeys(all_terms))
        vectors = {}
        requests = 0
        for offset in range(0, len(terms), EMBEDDING_BATCH_SIZE):
            batch = terms[offset : offset + EMBEDDING_BATCH_SIZE]
            embeddings = await runtime.context["embedding_client"].aembed_documents(
                batch
            )
            requests += 1
            if len(embeddings) != len(batch) or any(
                not vector for vector in embeddings
            ):
                raise ValueError("Embedding 返回向量数量不匹配或向量为空")
            vectors.update(zip(batch, embeddings, strict=True))
        logger.info(
            "Embedding elapsed_ms={:.1f} raw_terms={} unique_terms={} reused_terms={} requests={}",
            (perf_counter() - started) * 1000,
            len(all_terms),
            len(terms),
            len(all_terms) - len(terms),
            requests,
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return {"term_embeddings": vectors}
    except Exception as exc:
        logger.error(
            "Embedding failed elapsed_ms={:.1f}: {}",
            (perf_counter() - started) * 1000,
            exc,
        )
        writer({"type": "progress", "step": step, "status": "error"})
        raise
