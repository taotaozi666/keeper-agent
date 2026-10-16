/** 简洁模式：默认只展示当前步骤，展开可查看已发生步骤。 */
import { Check, ChevronDown, Circle, LoaderCircle, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { cn } from "../lib/format";
import { progressSummary } from "../lib/progress";
import type { ChatMessage, StepState } from "../types/agent";

type Props = {
  steps?: StepState[];
  status: ChatMessage["status"];
  hasResult: boolean;
};

export function ProgressList({ steps = [], status, hasResult }: Props) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const isStreaming = status === "streaming";
  const title = progressSummary(steps, status, hasResult);

  // 完成、失败或用户中止时收起列表，让结果成为主要内容；仍可再次展开。
  useEffect(() => {
    if (!isStreaming) setExpanded(false);
  }, [isStreaming]);

  return (
    <div className={cn("text-sm", !isStreaming && "mb-3")}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        disabled={steps.length === 0}
        aria-expanded={expanded}
        aria-controls={listId}
        className="group flex max-w-full items-center gap-2 rounded px-1 py-1 text-left text-ink/55 transition hover:bg-ink/5 hover:text-ink/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40 disabled:cursor-default"
      >
        {isStreaming ? (
          <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-moss" aria-hidden="true" />
        ) : status === "error" ? (
          <X className="h-4 w-4 shrink-0 text-tomato" aria-hidden="true" />
        ) : hasResult ? (
          <Check className="h-4 w-4 shrink-0 text-moss" aria-hidden="true" />
        ) : (
          <Circle className="h-4 w-4 shrink-0" aria-hidden="true" />
        )}
        <span className="min-w-0 break-words" aria-live="polite" aria-atomic="true">{title}</span>
        {!isStreaming && steps.length > 0 && <span className="shrink-0 text-xs text-ink/40">· {steps.length} 个步骤</span>}
        {steps.length > 0 && (
          <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        )}
      </button>

      <div id={listId} hidden={!expanded}>
        <ol aria-label="处理步骤" className="mb-3 ml-3 mt-3 max-h-64 space-y-3 overflow-y-auto border-l border-ink/10 py-1 pl-4 pr-2">
          {steps.map((step) => {
            const running = isStreaming && step.status === "running";
            const interrupted = !isStreaming && step.status === "running";
            const label = interrupted ? "未完成" : running ? "进行中" : step.status === "success" ? "已完成" : "未通过";
            return (
              <li key={step.step} className="flex items-center gap-2.5">
                {running ? <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-moss" aria-hidden="true" />
                  : interrupted ? <Circle className="h-3.5 w-3.5 shrink-0 text-ink/35" aria-hidden="true" />
                  : step.status === "success" ? <Check className="h-3.5 w-3.5 shrink-0 text-moss" aria-hidden="true" />
                  : <X className="h-3.5 w-3.5 shrink-0 text-tomato" aria-hidden="true" />}
                <span className={cn("min-w-0 flex-1 break-words", running ? "text-ink" : "text-ink/55")}>{step.step}</span>
                <span className="shrink-0 text-xs text-ink/40">{label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
