# Keeper 核心问数评测题与实际答案

生成时间：2026-10-16T16:55:01+08:00。答案来自本地数据库只读一致性快照，不调用 LLM。

## 数据与统一口径

数据库版本：8.0.46；订单日期范围：20250101 至 20250331。

| 表           | 行数 |
| ------------ | ---: |
| dim_region   |    6 |
| dim_customer |   20 |
| dim_product  |   15 |
| dim_date     |   90 |
| fact_order   |  115 |

- 金额单位沿用演示库（元），金额及百分数显示两位小数；销量单位为件。
- 订单数按订单编号去重，成交客户数按客户编号去重。
- GMV / 销售额为订单金额之和；演示表没有退款、状态或税费字段，不额外推断扣除规则。
- AOV 为订单总金额 ÷ 去重订单数，与商品平均单价区分。
- 答案只适用于本次数据快照，数据改变后需重新核验。
- 本集 20 题均有明确执行口径，暂不覆盖需要澄清或应拒绝的问题。
- 这些答案是手写参考 SQL 的实际执行结果，不代表 Agent 已通过 20 题；空结果题需人工检查 SQL 条件，不能只凭结果为空判定正确。

数据指纹（SHA-256）：`0ad0765ea11e11b1995a8e8eb886b738e1139673182a0e51c692cc78fc130f64`。

## 题目索引

| 编号       | 问题                                                                                                                                 |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| keeper_001 | 查询品牌为华为的商品编号、商品名称和品类。                                                                                           |
| keeper_002 | 列出手机数码品类的商品编号、商品名称和品牌，按商品编号升序排列。                                                                     |
| keeper_003 | 查询华东大区包含哪些省份，返回地区编号、省份和大区，按地区编号升序排列。                                                             |
| keeper_004 | 统计 2025 年第一季度的订单数、销量和 GMV。                                                                                           |
| keeper_005 | 按月份统计 2025 年第一季度的订单数、销量和销售额，按月份升序排列。                                                                   |
| keeper_006 | 统计 2025 年第一季度各大区的 GMV，按 GMV 降序排列；金额相同时按大区名称升序排列。                                                    |
| keeper_007 | 统计 2025 年 3 月各商品品类的销量和销售额，按品类名称升序排列。                                                                      |
| keeper_008 | 查询华东地区 2025 年第一季度销售额最高的前 5 个商品，返回商品编号、名称和销售额；金额相同时按商品编号升序排列。                      |
| keeper_009 | 统计黄金会员在 2025 年第一季度的订单数、GMV 和客单价。                                                                               |
| keeper_010 | 按会员等级统计 2025 年第一季度的订单数、GMV 和客单价，按 GMV 降序排列；金额相同时按等级名称升序排列。                                |
| keeper_011 | 统计 2025 年第一季度各商品品类的订单数和平均订单金额，按平均订单金额降序排列；相同时按品类名称升序排列。                             |
| keeper_012 | 统计 2025 年 3 月华为品牌在各大区的销量和销售额，按销售额降序排列；金额相同时按大区名称升序排列。                                    |
| keeper_013 | 统计 2025 年第一季度各省份的销售额，按销售额降序排列；金额相同时按省份名称升序排列。                                                 |
| keeper_014 | 查询 2025 年第一季度消费金额最高的前 5 位客户，返回客户编号、姓名和消费金额；金额相同时按客户编号升序排列。                          |
| keeper_015 | 统计 2025 年 3 月各大区的成交客户数，按客户数降序排列；相同时按大区名称升序排列。                                                    |
| keeper_016 | 统计 2025 年 1 月 1 日至 1 月 7 日每天的订单数和 GMV，包含起止日期，按日期升序排列。                                                 |
| keeper_017 | 统计 2025 年第一季度各商品品类的销售额及其占整体销售额的百分比，百分比保留两位小数，按销售额降序排列；金额相同时按品类名称升序排列。 |
| keeper_018 | 计算 2025 年 3 月相较 2 月的 GMV 环比，返回 2 月 GMV、3 月 GMV、增加金额和环比增长百分数，金额和百分数保留两位小数。                 |
| keeper_019 | 统计 2025 年第二季度的订单数和 GMV；如果没有订单，订单数和 GMV 都返回 0。                                                            |
| keeper_020 | 查询 2025 年 4 月的订单明细，返回订单编号、商品名称和订单金额，按订单编号升序排列。                                                  |

## keeper_001 · 查询品牌为华为的商品编号、商品名称和品类。

**口径：** 只按品牌精确筛选，不要求商品有订单。

**实际答案：**

| 商品编号 | 商品名称    | 品类     |
| -------- | ----------- | -------- |
| P003     | Mate 60 Pro | 手机数码 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT product_id AS `商品编号`, product_name AS `商品名称`, category AS `品类`
FROM dim_product WHERE brand = '华为' ORDER BY product_id;
```

</details>

## keeper_002 · 列出手机数码品类的商品编号、商品名称和品牌，按商品编号升序排列。

**口径：** 商品清单来自商品维表，不通过订单筛选。

**实际答案：**

| 商品编号 | 商品名称                 | 品牌   |
| -------- | ------------------------ | ------ |
| P001     | iPhone 15 Pro            | 苹果   |
| P002     | Galaxy S24 Ultra         | 三星   |
| P003     | Mate 60 Pro              | 华为   |
| P014     | Kindle Paperwhite 电子书 | 亚马逊 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT product_id AS `商品编号`, product_name AS `商品名称`, brand AS `品牌`
FROM dim_product WHERE category = '手机数码' ORDER BY product_id;
```

</details>

## keeper_003 · 查询华东大区包含哪些省份，返回地区编号、省份和大区，按地区编号升序排列。

**口径：** 以当前地区维表记录为准，不推断库中未收录的省份。

**实际答案：**

| 地区编号 | 省份   | 大区 |
| -------- | ------ | ---- |
| R002     | 浙江省 | 华东 |
| R005     | 上海市 | 华东 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT region_id AS `地区编号`, province AS `省份`, region_name AS `大区`
FROM dim_region WHERE region_name = '华东' ORDER BY region_id;
```

</details>

## keeper_004 · 统计 2025 年第一季度的订单数、销量和 GMV。

**口径：** 订单数按订单编号去重；销量为购买数量之和；GMV 为订单金额之和。

**实际答案：**

| 订单数 | 销量   | GMV      |
| ------ | ------ | -------- |
| 115    | 622.00 | 279159.5 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id WHERE d.year = 2025 AND d.quarter = 'Q1';
```

</details>

## keeper_005 · 按月份统计 2025 年第一季度的订单数、销量和销售额，按月份升序排列。

**口径：** 销售额采用 GMV 口径；仅返回有订单的月份。

**实际答案：**

| 月份 | 订单数 | 销量   | 销售额   |
| ---- | ------ | ------ | -------- |
| 1    | 40     | 149.00 | 109030.5 |
| 2    | 33     | 151.00 | 80009.0  |
| 3    | 42     | 322.00 | 90120.0  |

<details>
<summary>参考 SQL</summary>

```sql
SELECT d.month AS `月份`, COUNT(DISTINCT o.order_id) AS `订单数`,
       SUM(o.order_quantity) AS `销量`, ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY d.month ORDER BY d.month;
```

</details>

## keeper_006 · 统计 2025 年第一季度各大区的 GMV，按 GMV 降序排列；金额相同时按大区名称升序排列。

**口径：** 大区按 region_name 合并；同一大区可以包含多个省份。

**实际答案：**

| 大区 | GMV      |
| ---- | -------- |
| 华东 | 107373.0 |
| 华南 | 70202.0  |
| 华北 | 41099.5  |
| 西南 | 31528.0  |
| 华中 | 28957.0  |

<details>
<summary>参考 SQL</summary>

```sql
SELECT r.region_name AS `大区`, ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_region r ON o.region_id = r.region_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY r.region_name ORDER BY `GMV` DESC, r.region_name ASC;
```

</details>

## keeper_007 · 统计 2025 年 3 月各商品品类的销量和销售额，按品类名称升序排列。

**口径：** 销量为 SUM(order_quantity)，不是订单数；销售额为订单金额之和。

**实际答案：**

| 商品品类 | 销量   | 销售额  |
| -------- | ------ | ------- |
| 休闲零食 | 156.00 | 630.0   |
| 家用电器 | 6.00   | 19196.0 |
| 手机数码 | 10.00  | 62190.0 |
| 服饰     | 7.00   | 2593.0  |
| 鞋靴     | 4.00   | 4396.0  |
| 食品饮料 | 139.00 | 1115.0  |

<details>
<summary>参考 SQL</summary>

```sql
SELECT p.category AS `商品品类`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id WHERE d.year = 2025 AND d.month = 3
GROUP BY p.category ORDER BY p.category;
```

</details>

## keeper_008 · 查询华东地区 2025 年第一季度销售额最高的前 5 个商品，返回商品编号、名称和销售额；金额相同时按商品编号升序排列。

**口径：** 按商品编号聚合；排名限于华东地区第一季度订单。

**实际答案：**

| 商品编号 | 商品名称          | 销售额  |
| -------- | ----------------- | ------- |
| P002     | Galaxy S24 Ultra  | 28497.0 |
| P003     | Mate 60 Pro       | 27996.0 |
| P001     | iPhone 15 Pro     | 17998.0 |
| P004     | 戴森 V15 吸尘器   | 10998.0 |
| P005     | 美的空调 KFR-35GW | 6400.0  |

<details>
<summary>参考 SQL</summary>

```sql
SELECT p.product_id AS `商品编号`, p.product_name AS `商品名称`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id JOIN dim_region r ON o.region_id = r.region_id
WHERE d.year = 2025 AND d.quarter = 'Q1' AND r.region_name = '华东'
GROUP BY p.product_id, p.product_name ORDER BY `销售额` DESC, p.product_id ASC LIMIT 5;
```

</details>

## keeper_009 · 统计黄金会员在 2025 年第一季度的订单数、GMV 和客单价。

**口径：** 会员等级使用当前客户维表；客单价为订单总金额除以去重订单数，保留两位小数。

**实际答案：**

| 订单数 | GMV      | 客单价  |
| ------ | -------- | ------- |
| 34     | 100178.5 | 2946.43 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, ROUND(SUM(o.order_amount), 2) AS `GMV`,
       ROUND(SUM(o.order_amount) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2) AS `客单价`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_customer c ON o.customer_id = c.customer_id
WHERE d.year = 2025 AND d.quarter = 'Q1' AND c.member_level = '黄金';
```

</details>

## keeper_010 · 按会员等级统计 2025 年第一季度的订单数、GMV 和客单价，按 GMV 降序排列；金额相同时按等级名称升序排列。

**口径：** 客单价在每个会员等级内独立计算，不使用整体客单价。

**实际答案：**

| 会员等级 | 订单数 | GMV      | 客单价  |
| -------- | ------ | -------- | ------- |
| 黄金     | 34     | 100178.5 | 2946.43 |
| 白银     | 30     | 71094.0  | 2369.8  |
| 铂金     | 25     | 57679.0  | 2307.16 |
| 青铜     | 26     | 50208.0  | 1931.08 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT c.member_level AS `会员等级`, COUNT(DISTINCT o.order_id) AS `订单数`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`, ROUND(SUM(o.order_amount) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2) AS `客单价`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_customer c ON o.customer_id = c.customer_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY c.member_level ORDER BY `GMV` DESC, c.member_level ASC;
```

</details>

## keeper_011 · 统计 2025 年第一季度各商品品类的订单数和平均订单金额，按平均订单金额降序排列；相同时按品类名称升序排列。

**口径：** 平均订单金额采用 AOV 口径，不是金额除以购买件数。

**实际答案：**

| 商品品类 | 订单数 | 平均订单金额 |
| -------- | ------ | ------------ |
| 手机数码 | 29     | 6716.24      |
| 家用电器 | 19     | 3199.37      |
| 鞋靴     | 12     | 1099.0       |
| 服饰     | 12     | 556.92       |
| 食品饮料 | 22     | 113.18       |
| 休闲零食 | 21     | 59.02        |

<details>
<summary>参考 SQL</summary>

```sql
SELECT p.category AS `商品品类`, COUNT(DISTINCT o.order_id) AS `订单数`,
       ROUND(SUM(o.order_amount) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2) AS `平均订单金额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY p.category ORDER BY `平均订单金额` DESC, p.category ASC;
```

</details>

## keeper_012 · 统计 2025 年 3 月华为品牌在各大区的销量和销售额，按销售额降序排列；金额相同时按大区名称升序排列。

**口径：** 只统计有华为订单的大区，不补齐零成交大区。

**实际答案：**

| 大区 | 销量 | 销售额  |
| ---- | ---- | ------- |
| 华东 | 3.00 | 20997.0 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT r.region_name AS `大区`, SUM(o.order_quantity) AS `销量`,
       ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id JOIN dim_region r ON o.region_id = r.region_id
WHERE d.year = 2025 AND d.month = 3 AND p.brand = '华为'
GROUP BY r.region_name ORDER BY `销售额` DESC, r.region_name ASC;
```

</details>

## keeper_013 · 统计 2025 年第一季度各省份的销售额，按销售额降序排列；金额相同时按省份名称升序排列。

**口径：** 分组粒度为省份，不是大区。

**实际答案：**

| 省份   | 销售额  |
| ------ | ------- |
| 广东省 | 70202.0 |
| 上海市 | 60210.0 |
| 浙江省 | 47163.0 |
| 北京市 | 41099.5 |
| 四川省 | 31528.0 |
| 湖北省 | 28957.0 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT r.province AS `省份`, ROUND(SUM(o.order_amount), 2) AS `销售额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_region r ON o.region_id = r.region_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY r.province ORDER BY `销售额` DESC, r.province ASC;
```

</details>

## keeper_014 · 查询 2025 年第一季度消费金额最高的前 5 位客户，返回客户编号、姓名和消费金额；金额相同时按客户编号升序排列。

**口径：** 按客户编号聚合，避免同名客户混合。

**实际答案：**

| 客户编号 | 姓名 | 消费金额 |
| -------- | ---- | -------- |
| C001     | 李伟 | 20764.5  |
| C010     | 徐浩 | 19694.0  |
| C017     | 何娜 | 19644.0  |
| C015     | 高梅 | 19500.0  |
| C014     | 胡杰 | 18982.5  |

<details>
<summary>参考 SQL</summary>

```sql
SELECT c.customer_id AS `客户编号`, c.customer_name AS `姓名`,
       ROUND(SUM(o.order_amount), 2) AS `消费金额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_customer c ON o.customer_id = c.customer_id WHERE d.year = 2025 AND d.quarter = 'Q1'
GROUP BY c.customer_id, c.customer_name ORDER BY `消费金额` DESC, c.customer_id ASC LIMIT 5;
```

</details>

## keeper_015 · 统计 2025 年 3 月各大区的成交客户数，按客户数降序排列；相同时按大区名称升序排列。

**口径：** 客户在同一大区内去重；跨大区客户可以分别计入，不要求各区之和等于整体去重客户数。

**实际答案：**

| 大区 | 成交客户数 |
| ---- | ---------- |
| 华东 | 7          |
| 华南 | 4          |
| 华北 | 3          |
| 西南 | 3          |
| 华中 | 2          |

<details>
<summary>参考 SQL</summary>

```sql
SELECT r.region_name AS `大区`, COUNT(DISTINCT o.customer_id) AS `成交客户数`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_region r ON o.region_id = r.region_id WHERE d.year = 2025 AND d.month = 3
GROUP BY r.region_name ORDER BY `成交客户数` DESC, r.region_name ASC;
```

</details>

## keeper_016 · 统计 2025 年 1 月 1 日至 1 月 7 日每天的订单数和 GMV，包含起止日期，按日期升序排列。

**口径：** 两端日期均包含；日期以 yyyyMMdd 整数表示，仅返回有订单的日期。

**实际答案：**

| 日期     | 订单数 | GMV     |
| -------- | ------ | ------- |
| 20250101 | 2      | 15998.0 |
| 20250102 | 2      | 1024.0  |
| 20250103 | 2      | 1459.0  |
| 20250104 | 1      | 40.0    |
| 20250105 | 2      | 499.0   |
| 20250106 | 1      | 9499.0  |
| 20250107 | 1      | 35.0    |

<details>
<summary>参考 SQL</summary>

```sql
SELECT d.date_id AS `日期`, COUNT(DISTINCT o.order_id) AS `订单数`,
       ROUND(SUM(o.order_amount), 2) AS `GMV`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id WHERE d.date_id BETWEEN 20250101 AND 20250107
GROUP BY d.date_id ORDER BY d.date_id;
```

</details>

## keeper_017 · 统计 2025 年第一季度各商品品类的销售额及其占整体销售额的百分比，百分比保留两位小数，按销售额降序排列；金额相同时按品类名称升序排列。

**口径：** 分母为同一季度全部品类销售额；结果如 12.34 表示 12.34%，不是 0.1234；逐项四舍五入后不保证精确合计 100。

**实际答案：**

| 商品品类 | 销售额   | 占比百分数 |
| -------- | -------- | ---------- |
| 手机数码 | 194771.0 | 69.77      |
| 家用电器 | 60788.0  | 21.78      |
| 鞋靴     | 13188.0  | 4.72       |
| 服饰     | 6683.0   | 2.39       |
| 食品饮料 | 2490.0   | 0.89       |
| 休闲零食 | 1239.5   | 0.44       |

<details>
<summary>参考 SQL</summary>

```sql
WITH category_sales AS (
  SELECT p.category, SUM(o.order_amount) AS amount
  FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id WHERE d.year = 2025 AND d.quarter = 'Q1' GROUP BY p.category
)
SELECT category AS `商品品类`, ROUND(amount, 2) AS `销售额`,
       ROUND(amount * 100.0 / NULLIF(SUM(amount) OVER (), 0), 2) AS `占比百分数`
FROM category_sales ORDER BY `销售额` DESC, category ASC;
```

</details>

## keeper_018 · 计算 2025 年 3 月相较 2 月的 GMV 环比，返回 2 月 GMV、3 月 GMV、增加金额和环比增长百分数，金额和百分数保留两位小数。

**口径：** 环比为 (3月GMV-2月GMV)/2月GMV×100；分母为零时返回 NULL；增加金额允许为负。

**实际答案：**

| 2月GMV  | 3月GMV  | 增加金额 | 环比增长百分数 |
| ------- | ------- | -------- | -------------- |
| 80009.0 | 90120.0 | 10111.0  | 12.64          |

<details>
<summary>参考 SQL</summary>

```sql
WITH monthly AS (
  SELECT SUM(CASE WHEN d.month = 2 THEN o.order_amount ELSE 0 END) AS feb,
         SUM(CASE WHEN d.month = 3 THEN o.order_amount ELSE 0 END) AS mar
  FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id WHERE d.year = 2025 AND d.month IN (2, 3)
)
SELECT ROUND(feb, 2) AS `2月GMV`, ROUND(mar, 2) AS `3月GMV`,
       ROUND(mar - feb, 2) AS `增加金额`,
       ROUND((mar - feb) * 100.0 / NULLIF(feb, 0), 2) AS `环比增长百分数`
FROM monthly;
```

</details>

## keeper_019 · 统计 2025 年第二季度的订单数和 GMV；如果没有订单，订单数和 GMV 都返回 0。

**口径：** 无订单时仍返回一行，COUNT 为 0，SUM 的 NULL 通过 COALESCE 转为 0。

**实际答案：**

| 订单数 | GMV |
| ------ | --- |
| 0      | 0.0 |

<details>
<summary>参考 SQL</summary>

```sql
SELECT COUNT(DISTINCT o.order_id) AS `订单数`, COALESCE(ROUND(SUM(o.order_amount), 2), 0) AS `GMV`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id WHERE d.year = 2025 AND d.quarter = 'Q2';
```

</details>

## keeper_020 · 查询 2025 年 4 月的订单明细，返回订单编号、商品名称和订单金额，按订单编号升序排列。

**口径：** 无订单时返回空列表，不伪造一行零金额记录。

**实际答案：**

无符合条件的记录，返回 `[]`。

<details>
<summary>参考 SQL</summary>

```sql
SELECT o.order_id AS `订单编号`, p.product_name AS `商品名称`, ROUND(o.order_amount, 2) AS `订单金额`
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id JOIN dim_product p ON o.product_id = p.product_id WHERE d.year = 2025 AND d.month = 4
ORDER BY o.order_id;
```

</details>
