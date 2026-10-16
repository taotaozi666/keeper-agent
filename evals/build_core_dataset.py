"""从本地演示数据库的只读一致性快照生成 20 题及参考答案。

运行：python -m evals.build_core_dataset
仅执行下面预定义的 SELECT 查询，不调用模型、不修改数据库。
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app.clients.mysql_client_manager import dw_mysql_client_manager

ROOT = Path(__file__).resolve().parent
Q1 = "d.year = 2025 AND d.quarter = 'Q1'"
MARCH = "d.year = 2025 AND d.month = 3"
DATE_JOIN = "JOIN dim_date d ON o.date_id = d.date_id"
PRODUCT_JOIN = "JOIN dim_product p ON o.product_id = p.product_id"
REGION_JOIN = "JOIN dim_region r ON o.region_id = r.region_id"
CUSTOMER_JOIN = "JOIN dim_customer c ON o.customer_id = c.customer_id"
AOV = "ROUND(SUM(o.order_amount) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2)"


def question(number, query, sql, tags, rules, *, ordered=False):
    return {
        "id": f"keeper_{number:03d}",
        "question": query,
        "expected_action": "execute",
        "tags": tags,
        "business_rules": rules,
        "reference_sql": sql.strip() + ";",
        "comparison": {"order_sensitive": ordered, "numeric_absolute_tolerance": 0.01},
    }


QUESTIONS = [
    question(
        1,
        "查询品牌为华为的商品编号、商品名称和品类。",
        """
SELECT product_id AS `商品编号`, product_name AS `商品名称`, category AS `品类`
FROM dim_product WHERE brand = '华为' ORDER BY product_id
""",
        ["single_table", "exact_value"],
        ["只按品牌精确筛选，不要求商品有订单。"],
        ordered=True,
    ),
    question(
        2,
        "列出手机数码品类的商品编号、商品名称和品牌，按商品编号升序排列。",
        """
SELECT product_id AS `商品编号`, product_name AS `商品名称`, brand AS `品牌`
FROM dim_product WHERE category = '手机数码' ORDER BY product_id
""",
        ["single_table", "category", "sort"],
        ["商品清单来自商品维表，不通过订单筛选。"],
        ordered=True,
    ),
    question(
        3,
        "查询华东大区包含哪些省份，返回地区编号、省份和大区，按地区编号升序排列。",
        """
SELECT region_id AS `地区编号`, province AS `省份`, region_name AS `大区`
FROM dim_region WHERE region_name = '华东' ORDER BY region_id
""",
        ["single_table", "exact_value"],
        ["以当前地区维表记录为准，不推断库中未收录的省份。"],
        ordered=True,
    ),
    question(
        4,
        "统计 2025 年第一季度的订单数、销量和 GMV。",
        f"""
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o {DATE_JOIN} WHERE {Q1}
""",
        ["aggregation", "distinct", "metric", "quarter"],
        ["订单数按订单编号去重；销量为购买数量之和；GMV 为订单金额之和。"],
    ),
    question(
        5,
        "按月份统计 2025 年第一季度的订单数、销量和销售额，按月份升序排列。",
        f"""
SELECT d.month AS `月份`, COUNT(DISTINCT o.order_id) AS `订单数`,
       SUM(o.order_quantity) AS `销量`, ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o {DATE_JOIN} WHERE {Q1}
GROUP BY d.month ORDER BY d.month
""",
        ["group_by", "time", "aggregation"],
        ["销售额采用 GMV 口径；仅返回有订单的月份。"],
        ordered=True,
    ),
    question(
        6,
        "统计 2025 年第一季度各大区的 GMV，按 GMV 降序排列；金额相同时按大区名称升序排列。",
        f"""
SELECT r.region_name AS `大区`, ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o {DATE_JOIN} {REGION_JOIN} WHERE {Q1}
GROUP BY r.region_name ORDER BY `GMV` DESC, r.region_name ASC
""",
        ["join", "group_by", "metric", "sort"],
        ["大区按 region_name 合并；同一大区可以包含多个省份。"],
        ordered=True,
    ),
    question(
        7,
        "统计 2025 年 3 月各商品品类的销量和销售额，按品类名称升序排列。",
        f"""
SELECT p.category AS `商品品类`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} WHERE {MARCH}
GROUP BY p.category ORDER BY p.category
""",
        ["join", "group_by", "month", "multi_measure"],
        ["销量为 SUM(order_quantity)，不是订单数；销售额为订单金额之和。"],
        ordered=True,
    ),
    question(
        8,
        "查询华东地区 2025 年第一季度销售额最高的前 5 个商品，返回商品编号、名称和销售额；金额相同时按商品编号升序排列。",
        f"""
SELECT p.product_id AS `商品编号`, p.product_name AS `商品名称`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} {REGION_JOIN}
WHERE {Q1} AND r.region_name = '华东'
GROUP BY p.product_id, p.product_name ORDER BY `销售额` DESC, p.product_id ASC LIMIT 5
""",
        ["multi_join", "top_k", "filter"],
        ["按商品编号聚合；排名限于华东地区第一季度订单。"],
        ordered=True,
    ),
    question(
        9,
        "统计黄金会员在 2025 年第一季度的订单数、GMV 和客单价。",
        f"""
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, ROUND(SUM(o.order_amount), 2) AS `GMV`,
       {AOV} AS `客单价`
FROM fact_order o {DATE_JOIN} {CUSTOMER_JOIN}
WHERE {Q1} AND c.member_level = '黄金'
""",
        ["join", "exact_value", "aov", "distinct"],
        ["会员等级使用当前客户维表；客单价为订单总金额除以去重订单数，保留两位小数。"],
    ),
    question(
        10,
        "按会员等级统计 2025 年第一季度的订单数、GMV 和客单价，按 GMV 降序排列；金额相同时按等级名称升序排列。",
        f"""
SELECT c.member_level AS `会员等级`, COUNT(DISTINCT o.order_id) AS `订单数`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`, {AOV} AS `客单价`
FROM fact_order o {DATE_JOIN} {CUSTOMER_JOIN} WHERE {Q1}
GROUP BY c.member_level ORDER BY `GMV` DESC, c.member_level ASC
""",
        ["group_by", "aov", "metric"],
        ["客单价在每个会员等级内独立计算，不使用整体客单价。"],
        ordered=True,
    ),
    question(
        11,
        "统计 2025 年第一季度各商品品类的订单数和平均订单金额，按平均订单金额降序排列；相同时按品类名称升序排列。",
        f"""
SELECT p.category AS `商品品类`, COUNT(DISTINCT o.order_id) AS `订单数`,
       {AOV} AS `平均订单金额`
FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} WHERE {Q1}
GROUP BY p.category ORDER BY `平均订单金额` DESC, p.category ASC
""",
        ["aov", "group_by", "sort"],
        ["平均订单金额采用 AOV 口径，不是金额除以购买件数。"],
        ordered=True,
    ),
    question(
        12,
        "统计 2025 年 3 月华为品牌在各大区的销量和销售额，按销售额降序排列；金额相同时按大区名称升序排列。",
        f"""
SELECT r.region_name AS `大区`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} {REGION_JOIN}
WHERE {MARCH} AND p.brand = '华为'
GROUP BY r.region_name ORDER BY `销售额` DESC, r.region_name ASC
""",
        ["multi_join", "brand", "month"],
        ["只统计有华为订单的大区，不补齐零成交大区。"],
        ordered=True,
    ),
    question(
        13,
        "统计 2025 年第一季度各省份的销售额，按销售额降序排列；金额相同时按省份名称升序排列。",
        f"""
SELECT r.province AS `省份`, ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o {DATE_JOIN} {REGION_JOIN} WHERE {Q1}
GROUP BY r.province ORDER BY `销售额` DESC, r.province ASC
""",
        ["join", "province", "group_by"],
        ["分组粒度为省份，不是大区。"],
        ordered=True,
    ),
    question(
        14,
        "查询 2025 年第一季度消费金额最高的前 5 位客户，返回客户编号、姓名和消费金额；金额相同时按客户编号升序排列。",
        f"""
SELECT c.customer_id AS `客户编号`, c.customer_name AS `姓名`,
       ROUND(SUM(o.order_amount), 2) AS `消费金额`
FROM fact_order o {DATE_JOIN} {CUSTOMER_JOIN} WHERE {Q1}
GROUP BY c.customer_id, c.customer_name ORDER BY `消费金额` DESC, c.customer_id ASC LIMIT 5
""",
        ["top_k", "customer", "join"],
        ["按客户编号聚合，避免同名客户混合。"],
        ordered=True,
    ),
    question(
        15,
        "统计 2025 年 3 月各大区的成交客户数，按客户数降序排列；相同时按大区名称升序排列。",
        f"""
SELECT r.region_name AS `大区`, COUNT(DISTINCT o.customer_id) AS `成交客户数`
FROM fact_order o {DATE_JOIN} {REGION_JOIN} WHERE {MARCH}
GROUP BY r.region_name ORDER BY `成交客户数` DESC, r.region_name ASC
""",
        ["distinct", "customer", "group_by"],
        [
            "客户在同一大区内去重；跨大区客户可以分别计入，不要求各区之和等于整体去重客户数。"
        ],
        ordered=True,
    ),
    question(
        16,
        "统计 2025 年 1 月 1 日至 1 月 7 日每天的订单数和 GMV，包含起止日期，按日期升序排列。",
        f"""
SELECT d.date_id AS `日期`, COUNT(DISTINCT o.order_id) AS `订单数`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o {DATE_JOIN} WHERE d.date_id BETWEEN 20250101 AND 20250107
GROUP BY d.date_id ORDER BY d.date_id
""",
        ["date_range", "boundary", "daily"],
        ["两端日期均包含；日期以 yyyyMMdd 整数表示，仅返回有订单的日期。"],
        ordered=True,
    ),
    question(
        17,
        "统计 2025 年第一季度各商品品类的销售额及其占整体销售额的百分比，百分比保留两位小数，按销售额降序排列；金额相同时按品类名称升序排列。",
        f"""
WITH category_sales AS (
  SELECT p.category, SUM(o.order_amount) AS amount
  FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} WHERE {Q1} GROUP BY p.category
)
SELECT category AS `商品品类`, ROUND(amount, 2) AS `销售额`,
       ROUND(amount * 100.0 / NULLIF(SUM(amount) OVER (), 0), 2) AS `占比百分数`
FROM category_sales ORDER BY `销售额` DESC, category ASC
""",
        ["cte", "window", "percentage"],
        [
            "分母为同一季度全部品类销售额；结果如 12.34 表示 12.34%，不是 0.1234；逐项四舍五入后不保证精确合计 100。"
        ],
        ordered=True,
    ),
    question(
        18,
        "计算 2025 年 3 月相较 2 月的 GMV 环比，返回 2 月 GMV、3 月 GMV、增加金额和环比增长百分数，金额和百分数保留两位小数。",
        f"""
WITH monthly AS (
  SELECT SUM(CASE WHEN d.month = 2 THEN o.order_amount ELSE 0 END) AS feb,
         SUM(CASE WHEN d.month = 3 THEN o.order_amount ELSE 0 END) AS mar
  FROM fact_order o {DATE_JOIN} WHERE d.year = 2025 AND d.month IN (2, 3)
)
SELECT ROUND(feb, 2) AS `2月GMV`, ROUND(mar, 2) AS `3月GMV`,
       ROUND(mar - feb, 2) AS `增加金额`,
       ROUND((mar - feb) * 100.0 / NULLIF(feb, 0), 2) AS `环比增长百分数`
FROM monthly
""",
        ["cte", "month_over_month", "calculation"],
        ["环比为 (3月GMV-2月GMV)/2月GMV×100；分母为零时返回 NULL；增加金额允许为负。"],
    ),
    question(
        19,
        "统计 2025 年第二季度的订单数和 GMV；如果没有订单，订单数和 GMV 都返回 0。",
        f"""
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, COALESCE(ROUND(SUM(o.order_amount), 2), 0) AS `GMV`
FROM fact_order o {DATE_JOIN} WHERE d.year = 2025 AND d.quarter = 'Q2'
""",
        ["empty_result", "null_handling", "aggregation"],
        ["无订单时仍返回一行，COUNT 为 0，SUM 的 NULL 通过 COALESCE 转为 0。"],
    ),
    question(
        20,
        "查询 2025 年 4 月的订单明细，返回订单编号、商品名称和订单金额，按订单编号升序排列。",
        f"""
SELECT o.order_id AS `订单编号`, p.product_name AS `商品名称`, ROUND(o.order_amount, 2) AS `订单金额`
FROM fact_order o {DATE_JOIN} {PRODUCT_JOIN} WHERE d.year = 2025 AND d.month = 4
ORDER BY o.order_id
""",
        ["empty_result", "detail", "join"],
        ["无订单时返回空列表，不伪造一行零金额记录。"],
        ordered=True,
    ),
]


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported answer value: {type(value).__name__}")


def markdown(dataset):
    snapshot = dataset["snapshot"]
    date_range = snapshot["date_range"]
    period = f"{date_range['start_date']} 至 {date_range['end_date']}"
    lines = [
        "# Keeper 核心问数评测题与实际答案",
        "",
        f"生成时间：{dataset['generated_at']}。答案来自本地数据库只读一致性快照，不调用 LLM。",
        "",
        "## 数据与统一口径",
        "",
        f"数据库版本：{snapshot['database_version']}；订单日期范围：{period}。",
        "",
        "| 表 | 行数 |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {name} | {count} |" for name, count in snapshot["table_counts"].items()
    )
    lines.extend(
        [
            "",
            "- 金额单位沿用演示库（元），金额及百分数显示两位小数；销量单位为件。",
            "- 订单数按订单编号去重，成交客户数按客户编号去重。",
            "- GMV / 销售额为订单金额之和；演示表没有退款、状态或税费字段，不额外推断扣除规则。",
            "- AOV 为订单总金额 ÷ 去重订单数，与商品平均单价区分。",
            "- 答案只适用于本次数据快照，数据改变后需重新核验。",
            "- 本集 20 题均有明确执行口径，暂不覆盖需要澄清或应拒绝的问题。",
            "- 这些答案是手写参考 SQL 的实际执行结果，不代表 Agent 已通过 20 题；空结果题需人工检查 SQL 条件，不能只凭结果为空判定正确。",
            "",
            f"数据指纹（SHA-256）：`{snapshot['data_sha256']}`。",
            "",
            "## 题目索引",
            "",
            "| 编号 | 问题 |",
            "| --- | --- |",
        ]
    )
    lines.extend(f"| {item['id']} | {item['question']} |" for item in dataset["cases"])
    for item in dataset["cases"]:
        lines.extend(
            [
                "",
                f"## {item['id']} · {item['question']}",
                "",
                "**口径：** " + "；".join(item["business_rules"]),
                "",
                "**实际答案：**",
                "",
            ]
        )
        rows = item["expected_result"]
        if not rows:
            lines.append("无符合条件的记录，返回 `[]`。")
        else:
            columns = item["expected_columns"]
            lines.extend(
                [
                    "| " + " | ".join(columns) + " |",
                    "| " + " | ".join("---" for _ in columns) + " |",
                ]
            )
            for row in rows:

                def cell(value):
                    if value is None:
                        return "NULL"
                    if isinstance(value, Decimal):
                        return f"{value:.2f}"
                    return str(value).replace("|", "\\|").replace("\n", " ")

                lines.append(
                    "| " + " | ".join(cell(row[column]) for column in columns) + " |"
                )
        lines.extend(
            [
                "",
                "<details>",
                "<summary>参考 SQL</summary>",
                "",
                "```sql",
                item["reference_sql"],
                "```",
                "",
                "</details>",
            ]
        )
    return "\n".join(lines) + "\n"


async def main():
    dw_mysql_client_manager.init()
    try:
        async with dw_mysql_client_manager.session_factory() as session:
            await session.execute(
                text("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            )
            version = (await session.execute(text("SELECT VERSION()"))).scalar_one()
            counts = {}
            fingerprint = hashlib.sha256()
            for table, key in (
                ("dim_region", "region_id"),
                ("dim_customer", "customer_id"),
                ("dim_product", "product_id"),
                ("dim_date", "date_id"),
                ("fact_order", "order_id"),
            ):
                rows = [
                    dict(row)
                    for row in (
                        await session.execute(
                            text(f"SELECT * FROM {table} ORDER BY {key}")
                        )
                    ).mappings()
                ]
                counts[table] = len(rows)
                fingerprint.update(
                    json.dumps(
                        {"table": table, "rows": rows},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=json_default,
                    ).encode("utf-8")
                )
            date_range = dict(
                (
                    await session.execute(
                        text(
                            "SELECT MIN(date_id) AS start_date, MAX(date_id) AS end_date FROM fact_order"
                        )
                    )
                )
                .mappings()
                .one()
            )
            cases = []
            for case in QUESTIONS:
                result = await session.execute(text(case["reference_sql"]))
                columns = list(result.keys())
                rows = [dict(row) for row in result.mappings()]
                cases.append(
                    {
                        **case,
                        "expected_columns": columns,
                        "expected_row_count": len(rows),
                        "expected_result": rows,
                    }
                )
            dataset = {
                "version": "1.0",
                "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(
                    timespec="seconds"
                ),
                "snapshot": {
                    "database_version": version,
                    "table_counts": counts,
                    "date_range": date_range,
                    "data_sha256": fingerprint.hexdigest(),
                },
                "cases": cases,
            }
            # 所有 SELECT 成功后才写文件，防止留下半份答案。
            (ROOT / "core_queries.json").write_text(
                json.dumps(dataset, ensure_ascii=False, indent=2, default=json_default)
                + "\n",
                encoding="utf-8",
            )
            (ROOT / "core_queries.md").write_text(markdown(dataset), encoding="utf-8")
            await session.rollback()
            print(
                "Generated 20 questions and actual answers:", ROOT / "core_queries.md"
            )
            print("Snapshot:", counts, date_range)
            print("Answer row counts:", [case["expected_row_count"] for case in cases])
    finally:
        await dw_mysql_client_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
