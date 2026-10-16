/**
 * 聊天消息气泡组件
 * 组合展示用户问题、智能体回复、执行流程和结果表格
 */
import { Bot, Copy, UserRound } from "lucide-react";
import { FileCard } from "./FileCard";
import { ResultTable } from "./ResultTable";
import { StepRail } from "./StepRail";
import { ProgressList } from "./ProgressList";
import { cn, formatTime, toClipboardText } from "../lib/format";
import { resolveProgressView } from "../lib/progress";
import type { ChatMessage } from "../types/agent";

export function MessageBubble({ message, conversationId }: { message: ChatMessage; conversationId?: string | null }) {
  const isUser = message.role === "user";
  const compactProgress = !isUser && resolveProgressView(import.meta.env.VITE_PROGRESS_VIEW, import.meta.env.DEV) === "compact";
  const showText = !compactProgress || message.status !== "streaming";

  const copy = async () => {
    const text = message.result ? toClipboardText(message.result) : message.content;
    await navigator.clipboard.writeText(text);
  };

  return (
    <article aria-label={isUser ? "用户消息" : "AI 回复"} className={cn("group flex min-w-0 gap-3", isUser && "justify-end")}>
      {!isUser && (
        <div role="img" aria-label="AI 头像" className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-moss/10 text-moss">
          <Bot className="h-4 w-4" aria-hidden="true" />
        </div>
      )}

      <div className={cn("min-w-0 max-w-[calc(100%-44px)]", isUser ? "sm:max-w-[80%]" : "w-full sm:max-w-[90%]")}>
        <div
          className={cn(
            "relative min-w-0 max-w-full",
            isUser
              ? "rounded-[24px] bg-[#DEF3E5] px-5 py-3 text-ink"
              : "w-full rounded-[24px] bg-[#F2F2F3] px-4 py-3 text-ink sm:px-5",
          )}
        >
          {compactProgress && message.responseType !== "reply" && <ProgressList steps={message.steps} status={message.status} hasResult={message.result !== undefined || Boolean(message.results?.length)} />}

          {showText && <div className="flex items-start justify-between gap-3">
            <p className="whitespace-pre-wrap break-words text-[15px] leading-7">{message.content}</p>
            {!isUser && message.status !== "streaming" && (
              <button
                type="button"
                onClick={copy}
                className="shrink-0 rounded-full p-1.5 text-ink/45 opacity-0 outline-none transition hover:bg-ink/5 hover:text-ink focus:opacity-100 focus:ring-2 focus:ring-moss/40 group-hover:opacity-100"
                title="复制"
                aria-label="复制"
              >
                <Copy className="h-4 w-4" aria-hidden="true" />
              </button>
            )}
          </div>}

          {message.error && (
            <div className="mt-3 rounded-xl border border-tomato/30 bg-tomato/10 px-3 py-2 text-sm text-tomato">
              {message.error}
            </div>
          )}

          {!isUser && !compactProgress && <StepRail steps={message.steps} />}
          {!isUser && message.result !== undefined && <ResultTable data={message.result} />}
          {!isUser && message.results?.map(result => <div key={result.query_result_id} className="mt-4">
            <p className="text-xs text-ink/55">{result.query}{result.truncated ? ` · 共 ${result.row_count} 行，历史显示部分结果` : ""}</p>
            <ResultTable data={result.data} />
          </div>)}
          {!isUser && conversationId && message.files?.map(file => <FileCard key={file.id} file={file} conversationId={conversationId} />)}

          <div
            className={cn(
              "mt-3 text-xs",
              isUser ? "text-ink/35" : "text-ink/35",
            )}
          >
            {formatTime(message.createdAt)}
          </div>
        </div>
      </div>
      {isUser && (
        <div role="img" aria-label="用户头像" className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink/10 text-ink/65">
          <UserRound className="h-4 w-4" aria-hidden="true" />
        </div>
      )}
    </article>
  );
}
