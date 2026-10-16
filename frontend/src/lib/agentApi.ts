/**
 * 智能体接口客户端
 * 封装后端 /api/query SSE 流式接口请求与事件解析逻辑
 */
import type { AgentEvent, ConversationTurn } from "../types/agent";
import { consumeQueryStream } from "./sse";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

type QueryOptions = {
  signal?: AbortSignal;
  conversationId?: string | null;
  onEvent: (event: AgentEvent) => void;
};

export async function streamQuery(query: string, options: QueryOptions) {
  const response = await fetch(`${API_BASE_URL}/api/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ query, conversation_id: options.conversationId ?? null }),
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`接口请求失败：HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("浏览器未返回可读取的流式响应。");
  }

  await consumeQueryStream(response.body, options.onEvent);
}


export async function loadConversation(id: string, signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(id)}`, { signal });
  if (!response.ok) throw new Error(`恢复会话失败：HTTP ${response.status}，可点击新会话重新开始。`);
  return response.json() as Promise<{ turns: ConversationTurn[] }>;
}

export type ConversationSummary = { id: string; title: string; updated_at: string };

export async function listConversations(offset = 0, signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/conversations?limit=30&offset=${offset}`, { signal });
  if (!response.ok) throw new Error(`加载历史会话失败：HTTP ${response.status}`);
  return response.json() as Promise<{ items: ConversationSummary[]; has_more: boolean }>;
}


export async function changeConversationDeleted(id: string, deleted: boolean) {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(id)}${deleted ? "" : "/restore"}`, { method: deleted ? "DELETE" : "POST" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `操作失败：HTTP ${response.status}`);
  }
}


export async function downloadArtifact(conversationId: string, fileId: string, name: string) {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}/files/${encodeURIComponent(fileId)}/download`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `下载失败：HTTP ${response.status}`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
