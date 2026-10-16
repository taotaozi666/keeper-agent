"""校验失败达到修复上限后，终止查询并交由服务层输出错误事件。"""

from app.agent.state import DataAgentState

MAX_SQL_REPAIRS = 2


def route_after_validation(state: DataAgentState) -> str:
    if state["error"] is None:
        return "run_sql"
    if state.get("repair_count", 0) >= MAX_SQL_REPAIRS:
        return "sql_failure"
    return "correct_sql"


async def sql_failure(state: DataAgentState):
    raise ValueError(
        f"SQL 校验失败，已达到 {MAX_SQL_REPAIRS} 次修复上限：{state['error']}"
    )
