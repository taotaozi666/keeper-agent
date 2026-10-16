"""可选的请求内指标收集，不改变 API 事件协议。"""

from contextvars import ContextVar

metrics_context: ContextVar[list[dict] | None] = ContextVar(
    "metrics_context", default=None
)


def record_metric(metric: dict):
    collector = metrics_context.get()
    if collector is not None:
        collector.append(metric)
