/** 消费 SSE；result（包括 []）、clarification、reply 和 error 均为终态。 */
import type { AgentEvent } from "../types/agent";

function parseEvent(chunk: string): AgentEvent | null {
  const payload = chunk
    .split(/\r\n|\r|\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace(/^data: ?/, ""))
    .join("\n");
  if (!payload.trim()) return null;

  let event: unknown;
  try {
    event = JSON.parse(payload);
  } catch {
    throw new Error("无法解析问数接口的流式响应。");
  }
  if (event && typeof event === "object" && "type" in event) {
    if (event.type === "done" && "message" in event && typeof event.message === "string"
      && "results" in event && Array.isArray(event.results) && "files" in event && Array.isArray(event.files)) return event as AgentEvent;
    if (event.type === "artifact" && "file" in event && event.file && typeof event.file === "object"
      && "id" in event.file && typeof event.file.id === "string") return event as AgentEvent;
    if (event.type === "result" && "data" in event) return event as AgentEvent;
    if (event.type === "conversation" && "conversation_id" in event && typeof event.conversation_id === "string") return event as AgentEvent;
    if ((event.type === "error" || event.type === "clarification" || event.type === "reply") && "message" in event && typeof event.message === "string") {
      return event as AgentEvent;
    }
    if (event.type === "progress" && "step" in event && typeof event.step === "string"
      && "status" in event && ["running", "success", "error"].includes(String(event.status))) {
      return event as AgentEvent;
    }
  }
  throw new Error("问数接口返回了未知的事件格式。");
}

export async function consumeQueryStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AgentEvent) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  function deliver(chunk: string): boolean {
    const event = parseEvent(chunk);
    if (!event) return false;
    onEvent(event);
    return (event.type === "result" && event.terminal !== false) || event.type === "done" || event.type === "error" || event.type === "clarification" || event.type === "reply";
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        // 兼容最后一条事件没有双换行的旧服务。
        if (deliver(buffer)) return;
        throw new Error("响应已结束，但未收到查询结果，请重试。");
      }
      buffer += decoder.decode(value, { stream: true });
      // 支持 LF、CRLF、CR，保留跨网络包的 UTF-8 字符和分隔符。
      let separator: RegExpExecArray | null;
      while ((separator = /\r\n\r\n|\n\n|\r\r/.exec(buffer)) !== null) {
        const chunk = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        if (deliver(chunk)) return;
      }
    }
  } finally {
    // 终态后不再等待 EOF；清理失败不能覆盖已经收到的结果。
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
