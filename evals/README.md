# 批量问数评测

在项目根目录运行。Agent 模式直接调用现有 LangGraph，无需启动前端或 FastAPI；仍需 MySQL、Qdrant、Elasticsearch、Embedding 和模型接口可用。

## 常用命令

```powershell
# 只校验测试集结构，不连接数据库或模型
uv run python -m evals.run --dry-run

# 先跑前 3 题；真实调用模型
uv run python -m evals.run --limit 3

# 跑完整 20 题，每题最长 90 秒
uv run python -m evals.run --timeout 90

# 指定题目回归
uv run python -m evals.run --ids keeper_007 keeper_009

# 使用其他测试集
uv run python -m evals.run --dataset evals/core_queries.json

# 仅执行参考 SQL，检查答案及数据库快照，不调用模型
uv run python -m evals.run --reference-only

# 额外记录完整提示词与回复到本轮 agent.log
uv run python -m evals.run --limit 3 --log-conversations
```

默认顺序执行，单题错误、超时或答案不一致后继续下一题。超时会取消当前协程并关闭本题 Session，但不能保证服务商立刻停止计算或计费。需要停止整轮时可按 Ctrl+C，已经完成的题目不会丢失。

## 报告

每次创建独立目录 `evals/reports/日期-时间-编号/`（Asia/Shanghai），不会覆盖前一轮：

- `report.md`：汇总表及可展开的每题实际结果、预期结果和 SQL。
- `report.json`：完整记录，包含开始 / 结束时间、耗时、SQL 修正历史、实际 / 预期结果、错误、进度事件、节点及模型耗时、Token 用量。
- `results.jsonl`：每完成一题立即追加一行；可用于中断后恢复已完成记录。
- `agent.log`：本轮运行日志；完整模型对话默认关闭，传 `--log-conversations` 后开启。

每题结束后更新汇总报告，记录通过率、平均 / 中位 / P95 耗时及已报告的 Token 总量。缺失 Token 用量单独计数，不将未知值当成零消耗。模型失败且未取得响应的调用不会计入 `model_responses`。

状态：`passed`、`failed`（结果不一致）、`error`、`timeout`、`needs_review`。全部通过退出码为 0；有不一致、异常、超时或待确认时为 1。

报告模式为 `reference_only` 时，只说明参考 SQL 与已存答案一致，不能作为 Agent 准确率。

## 比较规则

- 比较查询结果，不比较 SQL 文本；允许语义等价写法。
- 默认严格检查列名，列出现顺序不影响比较。明确等价的别名可逐题配置 `column_aliases`，例如 `{"品类": "商品品类"}`，表示实际列名“品类”映射为预期“商品品类”。不要把不相关的列强行映射。
- `order_sensitive: true` 时逐行比较排序；否则按结果多重集合匹配，保留重复行数量。
- 数值按绝对容差比较；不自动将字符串、NULL 和数字混为一类。
- 预期和实际均为空时，Agent 模式标为 `needs_review`，需人工核对 SQL 条件，不能自动判为通过。
- 对现有演示集，每题先在同一只读一致性快照中核对五张表的数据指纹。数据不同则本题在模型调用前失败，防止旧答案误判。自定义测试集可不提供演示库专用的 `snapshot`。

当前运行器只支持 `expected_action: execute`。澄清、拒绝及文档问答类任务需要后续增加对应判定器。

## 添加测试题

复制现有 [core_queries.json](core_queries.json) 的结构，在 `cases` 中增加唯一 ID：

```json
{
  "id": "custom_001",
  "question": "查询所有商品的数量，列名为商品数。",
  "expected_action": "execute",
  "reference_sql": "SELECT COUNT(*) AS 商品数 FROM dim_product;",
  "expected_columns": ["商品数"],
  "expected_result": [{"商品数": 15}],
  "comparison": {
    "order_sensitive": false,
    "numeric_absolute_tolerance": 0
  }
}
```

预期答案应通过独立核验的参考 SQL 获得。运行器不会把参考答案或参考 SQL 提供给模型，仅传入 `question`。

离线测试：

```powershell
uv run python -m unittest test.test_agent_workflow test.test_eval_runner -v
```
