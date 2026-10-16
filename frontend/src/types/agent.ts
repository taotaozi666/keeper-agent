/**
 * 智能体类型定义
 * 定义问数智能体前端使用的 SSE 事件、流程步骤和聊天消息类型
 */
export type ProgressStatus = "running" | "success" | "error";

export type ProgressEvent = {
  type: "progress";
  step: string;
  status: ProgressStatus;
};

export type ResultEvent = {
  type: "result";
  data: unknown;
  terminal?: boolean;
  query?: string;
  query_result_id?: string;
};

export type ErrorEvent = {
  type: "error";
  message: string;
};

export type ConversationEvent = { type: "conversation"; conversation_id: string };
export type ClarificationEvent = { type: "clarification"; message: string };
export type ReplyEvent = { type: "reply"; message: string };
export type DownloadFile = { id: string; name: string; format: string; size: number; row_count: number; expires_at: string };
export type QueryResult = { query_result_id: string; query: string; data: unknown; row_count?: number; truncated?: boolean };
export type ArtifactEvent = { type: "artifact"; file: DownloadFile };
export type DoneEvent = { type: "done"; message: string; results: QueryResult[]; files: DownloadFile[]; error?: string; clarification?: boolean };
export type AgentEvent = ProgressEvent | ResultEvent | ErrorEvent | ConversationEvent | ClarificationEvent | ReplyEvent | ArtifactEvent | DoneEvent;

export type StepState = {
  step: string;
  status: ProgressStatus;
  updatedAt: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  responseType?: "reply" | "clarification" | "result";
  steps?: StepState[];
  result?: unknown;
  results?: QueryResult[];
  files?: DownloadFile[];
  error?: string;
};


export type ConversationTurn = {
  id: string; query: string; status: string; created_at: string;
  response: { type: string; data?: unknown; message?: string; truncated?: boolean; row_count?: number; results?: QueryResult[]; files?: DownloadFile[]; error?: string; clarification?: boolean } | null;
};
