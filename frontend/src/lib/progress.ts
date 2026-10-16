import type { ChatMessage, ProgressEvent, StepState } from "../types/agent";

export type ProgressView = "graph" | "compact";

export function resolveProgressView(value: string | undefined, isDev: boolean): ProgressView {
  if (value === "graph" || value === "compact") return value;
  return isDev ? "graph" : "compact";
}

/** 保持首次出现的顺序，完成或重试时原位更新，不让列表跳动。 */
export function upsertStep(steps: StepState[] = [], event: ProgressEvent): StepState[] {
  const next = [...steps];
  const index = next.findIndex((item) => item.step === event.step);
  // 同一毫秒内的并行事件也保持可判定的先后顺序。
  const updatedAt = Math.max(Date.now(), ...steps.map((item) => item.updatedAt + 1));
  const update = { step: event.step, status: event.status, updatedAt };
  if (index === -1) next.push(update);
  else next[index] = update;
  return next;
}

export function progressSummary(steps: StepState[], status: ChatMessage["status"], hasResult: boolean) {
  if (status === "error") return "处理未完成";
  if (status !== "streaming") return hasResult ? "已完成处理" : "处理已结束";
  // 并行节点中优先显示仍在执行且最近更新的步骤。
  const running = steps.filter((step) => step.status === "running");
  const latest = (running.length ? running : steps).reduce<StepState | undefined>(
    (current, step) => !current || step.updatedAt >= current.updatedAt ? step : current,
    undefined,
  );
  if (!latest) return "正在连接企业数据助手…";
  if (latest.status === "running") return `正在${latest.step}…`;
  if (latest.status === "error") return `${latest.step}未通过，等待后续处理…`;
  return `已完成${latest.step}`;
}
