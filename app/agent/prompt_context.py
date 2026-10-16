"""仅精简模型输入副本；保留原始状态和真实召回值，不截断业务定义。"""

from copy import deepcopy

from app.agent.state import DataAgentState

DIMENSION_EXAMPLES = 3


def prompt_tables(state: DataAgentState) -> list[dict]:
    tables = deepcopy(state["table_infos"])
    matched = {}
    for value in state.get("retrieved_value_infos", []):
        values = matched.setdefault(value.column_id, [])
        if value.value not in values:
            values.append(value.value)
    for table in tables:
        for column in table["columns"]:
            hits = matched.get(f"{table['name']}.{column['name']}", [])
            # 主外键和度量不传任意样例；真实命中值全部保留。
            examples = list(hits)
            if column["role"] not in ("primary_key", "foreign_key", "measure"):
                for example in column.get("examples", []):
                    if len(examples) >= max(DIMENSION_EXAMPLES, len(hits)):
                        break
                    if example not in examples:
                        examples.append(example)
            column["examples"] = examples
    return tables
