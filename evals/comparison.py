"""结果比较：列名显式映射、数值容差、顺序及重复行检查。"""

from decimal import Decimal
from numbers import Number


def compare_results(case: dict, actual) -> dict:
    expected = case["expected_result"]
    if not isinstance(actual, list) or any(not isinstance(row, dict) for row in actual):
        return {"match": False, "reason": "结果不是字典列表"}
    if len(actual) != len(expected):
        return {
            "match": False,
            "reason": f"行数不同：预期 {len(expected)}，实际 {len(actual)}",
        }
    if not expected:
        return {
            "match": True,
            "reason": "两者均为空，需人工核对 SQL 筛选条件",
            "needs_review": True,
        }
    aliases = case.get("column_aliases", {})
    columns = set(case["expected_columns"])
    normalized = []
    for row in actual:
        mapped = {aliases.get(name, name): value for name, value in row.items()}
        if len(mapped) != len(row) or set(mapped) != columns:
            return {
                "match": False,
                "reason": f"列名不同：预期 {sorted(columns)}，实际 {sorted(mapped)}",
            }
        normalized.append(mapped)
    tolerance = Decimal(
        str(case.get("comparison", {}).get("numeric_absolute_tolerance", 0))
    )

    def same_value(left, right):
        if left is None or right is None:
            return left is right
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        if isinstance(left, Number) and isinstance(right, Number):
            a, b = Decimal(str(left)), Decimal(str(right))
            return a.is_finite() and b.is_finite() and abs(a - b) <= tolerance
        return type(left) is type(right) and left == right

    def same_row(left, right):
        return all(same_value(left[column], right[column]) for column in columns)

    if case.get("comparison", {}).get("order_sensitive", False):
        for index, (left, right) in enumerate(zip(expected, normalized, strict=True)):
            if not same_row(left, right):
                return {"match": False, "reason": f"第 {index + 1} 行数值或排序不同"}
    else:
        # 二分图匹配保留重复行，并避免数值容差下贪心匹配误判。
        matches = {}

        def assign(index, seen):
            for candidate, row in enumerate(normalized):
                if candidate in seen or not same_row(expected[index], row):
                    continue
                seen.add(candidate)
                if candidate not in matches or assign(matches[candidate], seen):
                    matches[candidate] = index
                    return True
            return False

        for index in range(len(expected)):
            if not assign(index, set()):
                return {
                    "match": False,
                    "reason": f"无法匹配预期第 {index + 1} 行（含重复行校验）",
                }
    return {"match": True, "reason": "结果一致"}
