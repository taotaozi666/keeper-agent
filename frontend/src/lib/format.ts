import type { ChatMessage, ConversationTurn } from "../types/agent";
/**
 * 通用格式化工具
 * 提供 className 合并、时间格式化和查询结果文本化等通用工具函数
 */
export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatTime(timestamp: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

export function summarizeResult(data: unknown) {
  if (Array.isArray(data)) {
    return data.length > 0 ? `查询完成，共 ${data.length} 行结果。` : "查询完成，没有符合条件的数据。";
  }

  if (data && typeof data === "object") {
    return "查询完成，已返回结构化结果。";
  }

  if (data === null || data === undefined || data === "") {
    return "查询完成，结果为空。";
  }

  return `查询完成：${String(data)}`;
}

export function toClipboardText(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

/** 新事件和历史记录共用相同的消息含义，普通回复不能恢复为错误。 */
export function historyTurnToMessages(turn: ConversationTurn): ChatMessage[] {
  const response = turn.response;
  const done = response?.type === "done";
  const success = response?.type === "result";
  const textReply = response?.type === "reply" || response?.type === "clarification";
  return [
    { id: `${turn.id}-user`, role: "user", content: turn.query, createdAt: Date.parse(turn.created_at) },
    { id: turn.id, role: "assistant", createdAt: Date.parse(turn.created_at),
      status: done ? response.error ? "error" : "done" : success || textReply ? "done" : "error",
      responseType: done ? response.results?.length ? "result" : response.clarification ? "clarification" : "reply" : success ? "result" : textReply ? response.type as "reply" | "clarification" : undefined,
      content: done ? response.message ?? "处理完成。" : success ? (response.truncated ? `共 ${response.row_count} 行，历史仅保存部分结果。` : summarizeResult(response.data))
        : textReply ? response.message ?? "" : "本轮查询未完成。",
      results: done ? response.results : undefined,
      files: done ? response.files : undefined,
      result: success ? response.data : undefined,
      error: done ? response.error : success || textReply ? undefined : response?.message ?? "查询可能仍在执行或已中断，请稍后重试。" },
  ];
}
