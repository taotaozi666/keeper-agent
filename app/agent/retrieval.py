"""有界并发检索，任一请求失败时取消并等待其余请求，保持输入顺序。"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")
SEARCH_CONCURRENCY = 4
EMBEDDING_BATCH_SIZE = 20


async def bounded_map(
    items: list[T], operation: Callable[[T], Awaitable[R]]
) -> list[R]:
    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def invoke(item):
        async with semaphore:
            return await operation(item)

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(invoke(item)) for item in items]
    except ExceptionGroup as exc:
        # 保留常见单个服务错误的原始信息，让 SSE 可展示真实原因。
        if len(exc.exceptions) == 1:
            raise exc.exceptions[0] from exc
        raise
    return [task.result() for task in tasks]
