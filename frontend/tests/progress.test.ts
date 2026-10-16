import assert from "node:assert/strict";
import { test } from "node:test";
import { progressSummary, resolveProgressView, upsertStep } from "../src/lib/progress.ts";
import type { StepState } from "../src/types/agent.ts";

test("explicit configuration overrides development and production defaults", () => {
  assert.equal(resolveProgressView("graph", false), "graph");
  assert.equal(resolveProgressView("compact", true), "compact");
  assert.equal(resolveProgressView(undefined, true), "graph");
  assert.equal(resolveProgressView(undefined, false), "compact");
});

test("step completion and retry update in place without changing list order", () => {
  const original: StepState[] = [
    { step: "批量向量化检索词", status: "running", updatedAt: 1 },
    { step: "召回字段取值", status: "running", updatedAt: 2 },
  ];
  const complete = upsertStep(original, { type: "progress", step: "批量向量化检索词", status: "success" });
  assert.deepEqual(complete.map((step) => step.step), original.map((step) => step.step));
  assert.equal(original[0].status, "running");
  const retry = upsertStep(complete, { type: "progress", step: "批量向量化检索词", status: "running" });
  assert.equal(retry.length, 2);
  assert.equal(retry[0].status, "running");
});

test("collapsed summary prioritizes currently running parallel work", () => {
  const steps: StepState[] = [
    { step: "批量向量化检索词", status: "running", updatedAt: 1 },
    { step: "召回字段取值", status: "success", updatedAt: 3 },
  ];
  assert.equal(progressSummary(steps, "streaming", false), "正在批量向量化检索词…");
  steps.push({ step: "召回字段信息", status: "running", updatedAt: 4 });
  assert.equal(progressSummary(steps, "streaming", false), "正在召回字段信息…");
});

test("finished results, errors and cancellation do not show stale running text", () => {
  const steps: StepState[] = [{ step: "生成SQL", status: "running", updatedAt: 1 }];
  assert.equal(progressSummary(steps, "done", true), "已完成处理");
  assert.equal(progressSummary(steps, "error", false), "处理未完成");
  assert.equal(progressSummary(steps, "done", false), "处理已结束");
  assert.equal(progressSummary([], "streaming", false), "正在连接企业数据助手…");
});
