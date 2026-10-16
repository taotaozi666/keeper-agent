"""
问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。
"""

import json
from time import perf_counter

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    """封装一次问数查询所需的业务编排逻辑"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: HuggingFaceEndpointEmbeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
        conversation_repository=None,
        artifact_service=None,
    ):
        # MySQL 仓储分别负责元数据补全和真实数仓环境信息读取
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

        # 召回链路依赖的向量检索、Embedding 和全文检索能力由依赖层注入
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository
        self.conversation_repository = conversation_repository
        self.artifact_service = artifact_service

    async def _events(self, state):
        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )
        terminal = None
        async for mode, chunk in graph.astream(
            input=state, context=context, stream_mode=["custom", "updates"]
        ):
            if mode == "updates":
                for update in chunk.values():
                    if isinstance(update, dict):
                        state.update(update)
            elif chunk.get("type") in ("result", "clarification", "reply", "error"):
                terminal = chunk
            else:
                yield chunk
        if terminal is None:
            raise RuntimeError("查询结束但没有返回结果。")
        yield terminal

    async def query(self, query: str, conversation_id: str | None = None):
        started = perf_counter()
        status = "cancelled"
        state = DataAgentState(query=query, original_query=query)

        def encode(event):
            return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        try:
            if self.conversation_repository is None:
                async for event in self._events(state):
                    if event["type"] in ("result", "clarification", "reply"):
                        status = "success"
                    yield encode(event)
                status = "success"
                return
            repo = self.conversation_repository
            async with repo.acquire(conversation_id, query) as (
                session,
                conversation,
                turn,
            ):
                state.update(
                    memory_enabled=True,
                    conversation_context={
                        "active": conversation.active_context,
                        "pending": conversation.pending_clarification,
                    },
                )
                completed = False
                terminal = None
                try:
                    yield encode(
                        {"type": "conversation", "conversation_id": conversation.id}
                    )
                    if self.artifact_service is not None:
                        from app.agent.tool_agent import run_tool_agent

                        events = run_tool_agent(self, state, conversation.id, turn.id)
                    else:
                        events = self._events(state)
                    async for event in events:
                        if event.get("terminal") is not False and event["type"] in (
                            "result",
                            "clarification",
                            "reply",
                            "error",
                            "done",
                        ):
                            await repo.finish(
                                session,
                                conversation,
                                turn,
                                state,
                                event,
                                (perf_counter() - started) * 1000,
                            )
                            completed = True
                            status = turn.status
                            terminal = event
                        else:
                            yield encode(event)
                except Exception as exc:
                    message = str(exc) or "任务超时，请缩小范围后重试。"
                    event = {"type": "error", "message": message}
                    if state.get("tool_results") or state.get("tool_files"):
                        event = {
                            "type": "done",
                            "message": message,
                            "error": message,
                            "results": state.get("tool_results", []),
                            "files": state.get("tool_files", []),
                        }
                    await session.rollback()
                    await repo.finish(
                        session,
                        conversation,
                        turn,
                        state,
                        event,
                        (perf_counter() - started) * 1000,
                    )
                    completed = True
                    status = "failed"
                    terminal = event
                finally:
                    if not completed:
                        import anyio

                        with anyio.CancelScope(shield=True):
                            await session.rollback()
                            cancelled = {
                                "type": "error",
                                "message": "查询已取消或连接中断。",
                            }
                            if state.get("tool_results") or state.get("tool_files"):
                                cancelled = {
                                    "type": "done",
                                    "message": "任务已中断，已完成的结果已保存。",
                                    "error": "查询已取消或连接中断。",
                                    "results": state.get("tool_results", []),
                                    "files": state.get("tool_files", []),
                                }
                            await repo.finish(
                                session,
                                conversation,
                                turn,
                                state,
                                cancelled,
                                (perf_counter() - started) * 1000,
                            )
            if terminal is not None:
                yield encode(terminal)
        except Exception as exc:
            status = "failed"
            yield encode({"type": "error", "message": str(exc)})
        finally:
            logger.info(
                "Query status={} total_elapsed_ms={:.1f}",
                status,
                (perf_counter() - started) * 1000,
            )
