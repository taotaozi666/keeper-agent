import type { ChatMessage } from "../types/agent";

/** 连接错误不能覆盖已返回的结果或业务错误。 */
export function applyQueryError(message: ChatMessage, error: unknown): ChatMessage {
  if (message.status !== "streaming") return message;
  const isAbort = error instanceof Error && error.name === "AbortError";
  return {
    ...message,
    status: isAbort ? "done" : "error",
    content: isAbort ? "已停止本次查询。"
      : message.steps?.length ? "问数响应中断，请重试。" : "无法连接问数接口。",
    error: isAbort ? undefined : error instanceof Error ? error.message : String(error),
  };
}


