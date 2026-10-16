"""
问数查询接口路由

负责定义前端访问的 `/api/query` 接口，把 HTTP 请求交给 QueryService，
并把问数智能体执行过程以 SSE 形式持续返回给客户端。
路由层只处理请求体、依赖声明和响应类型，不直接创建 Repository 或执行图节点。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import FileResponse, StreamingResponse

from app.api.dependencies import (
    get_artifact_service,
    get_conversation_repository,
    get_query_service,
)
from app.api.schemas.query_schema import QuerySchema
from app.repositories.mysql.meta.conversation_repository import ConversationRepository
from app.services.artifact_service import ArtifactService
from app.services.query_service import QueryService

# 当前模块只维护查询相关接口，避免后续所有 API 都挤在 main.py 中
query_router = APIRouter()


@query_router.post("/api/query")
async def query_handler(
    # 请求体参数：FastAPI 会把前端 JSON 自动解析成 QuerySchema
    query: QuerySchema,
    # 服务依赖：FastAPI 会调用 get_query_service，递归组装它所需的仓储和客户端
    query_service: Annotated[QueryService, Depends(get_query_service)],
):
    """接收用户自然语言问题，并流式返回 LangGraph 工作流输出"""

    return StreamingResponse(
        # query.query 是用户问题字符串；QueryService.query 返回异步生成器供响应逐段消费
        query_service.query(
            query.query, str(query.conversation_id) if query.conversation_id else None
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@query_router.get("/api/conversations")
async def conversation_list(
    repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await repository.list_conversations(limit, offset)


@query_router.get("/api/conversations/{conversation_id}")
async def conversation_history(
    conversation_id: UUID,
    repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
):
    history = await repository.history(str(conversation_id))
    if history is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return history


@query_router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
):
    return await change_conversation_visibility(repository, conversation_id, True)


@query_router.post("/api/conversations/{conversation_id}/restore")
async def restore_conversation(
    conversation_id: UUID,
    repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
):
    return await change_conversation_visibility(repository, conversation_id, False)


async def change_conversation_visibility(repository, conversation_id, deleted):
    try:
        found = await repository.set_deleted(str(conversation_id), deleted)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": deleted}


@query_router.get("/api/conversations/{conversation_id}/files/{file_id}/download")
async def download_file(
    conversation_id: UUID,
    file_id: UUID,
    service: Annotated[ArtifactService, Depends(get_artifact_service)],
):
    try:
        item = await service.get(str(conversation_id), str(file_id))
        if item.kind not in ("xlsx", "csv"):
            raise FileNotFoundError("该文件不能直接下载，请先导出")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(410, str(exc)) from exc
    mime = (
        "text/csv; charset=utf-8"
        if item.kind == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        service.path(item),
        filename=item.name,
        media_type=mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
