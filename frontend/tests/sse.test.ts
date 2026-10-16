import assert from "node:assert/strict";
import { test } from "node:test";
import { consumeQueryStream } from "../src/lib/sse.ts";
import { applyQueryError } from "../src/lib/queryState.ts";
import { summarizeResult, historyTurnToMessages } from "../src/lib/format.ts";
import type { AgentEvent, ChatMessage } from "../src/types/agent.ts";

const encoder = new TextEncoder();

test("tool result continues through artifact until done", async () => {
  const payloads = [
    {type: "result", data: [], terminal: false},
    {type: "artifact", file: {id: "file1"}},
    {type: "done", message: "已导出", results: [], files: []},
  ];
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream(payloads.map(p => encoder.encode(`data: ${JSON.stringify(p)}\n\n`)), true), e => events.push(e));
  assert.equal(events.length, 3);
  await assert.rejects(consumeQueryStream(chunksStream([encoder.encode('data: {"type":"result","data":[],"terminal":false}\n\n')]), () => {}), /未收到查询结果/);
});

function chunksStream(chunks: Uint8Array[], failAfter = false) {
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < chunks.length) controller.enqueue(chunks[index++]);
      else if (failAfter) controller.error(new Error("network error"));
      else controller.close();
    },
  }, { highWaterMark: 0 });
}

test("empty result is terminal even if the connection fails afterwards", async () => {
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream([encoder.encode('data: {"type":"result","data":[]}\n\n')], true), (event) => events.push(event));
  assert.deepEqual(events, [{ type: "result", data: [] }]);
  assert.equal(summarizeResult([]), "查询完成，没有符合条件的数据。");
});

test("non-empty result does not wait for connection EOF", async () => {
  const events: AgentEvent[] = [];
  const data = [{ name: "华东" }];
  await consumeQueryStream(chunksStream([encoder.encode(`data: ${JSON.stringify({ type: "result", data })}\n\n`)], true), (event) => events.push(event));
  assert.deepEqual(events, [{ type: "result", data }]);
});

test("CRLF and UTF-8 characters split across network chunks are preserved", async () => {
  const source = encoder.encode('data: {"type":"progress","step":"执行SQL","status":"success"}\r\n\r\ndata: {"type":"result","data":[{"名称":"华北"}]}\r\n\r\n');
  const chunks = Array.from(source, (byte) => new Uint8Array([byte]));
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream(chunks), (event) => events.push(event));
  assert.equal(events.length, 2);
  assert.deepEqual(events[1], { type: "result", data: [{ 名称: "华北" }] });
});

test("server error is terminal and retains its business message", async () => {
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream([encoder.encode('data: {"type":"error","message":"SQL 校验失败"}\n\n')], true), (event) => events.push(event));
  assert.deepEqual(events, [{ type: "error", message: "SQL 校验失败" }]);
});

test("connection failure before result is still an error", async () => {
  await assert.rejects(consumeQueryStream(chunksStream([encoder.encode('data: {"type":"progress","step":"执行SQL","status":"running"}\n\n')], true), () => {}), /network error/);
});

test("EOF without a terminal event is not reported as successful", async () => {
  await assert.rejects(consumeQueryStream(chunksStream([encoder.encode(": heartbeat\n\n")]), () => {}), /未收到查询结果/);
});

test("final result without delimiter is accepted at normal EOF", async () => {
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream([encoder.encode('data: {"type":"result","data":[]}')]), (event) => events.push(event));
  assert.deepEqual(events, [{ type: "result", data: [] }]);
});

test("malformed events are reported", async () => {
  await assert.rejects(consumeQueryStream(chunksStream([encoder.encode('data: invalid\n\n')]), () => {}), /无法解析/);
  await assert.rejects(consumeQueryStream(chunksStream([encoder.encode('data: {"type":"result"}\n\n')]), () => {}), /未知的事件格式/);
});

function message(status: ChatMessage["status"]): ChatMessage {
  return { id: "test", role: "assistant", content: "原消息", createdAt: 0, status, steps: [] };
}

test("late network failure cannot overwrite empty result or server error", () => {
  const complete = { ...message("done"), result: [] };
  assert.equal(applyQueryError(complete, new Error("network error")), complete);
  const failure = { ...message("error"), error: "业务错误" };
  assert.equal(applyQueryError(failure, new Error("network error")), failure);
});

test("connection failure, interruption and user cancellation have distinct messages", () => {
  assert.equal(applyQueryError(message("streaming"), new Error("network error")).content, "无法连接问数接口。");
  const streaming: ChatMessage = { ...message("streaming"), steps: [{ step: "生成SQL", status: "running", updatedAt: 0 }] };
  assert.equal(applyQueryError(streaming, new Error("network error")).content, "问数响应中断，请重试。");
  assert.equal(applyQueryError(streaming, new DOMException("cancelled", "AbortError")).content, "已停止本次查询。");
});


test("conversation event is nonterminal and clarification is terminal", async () => {
  const events: AgentEvent[] = [];
  const source = [
    { type: "conversation", conversation_id: "session-1" },
    { type: "clarification", message: "请问哪个月份？" },
  ].map(event => encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
  await consumeQueryStream(chunksStream(source, true), event => events.push(event));
  assert.equal(events.length, 2);
  assert.deepEqual(events[1], { type: "clarification", message: "请问哪个月份？" });
});


test("ordinary reply is terminal and late network failure does not overwrite it", async () => {
  const events: AgentEvent[] = [];
  await consumeQueryStream(chunksStream([encoder.encode('data: {"type":"reply","message":"你好！"}\n\n')], true), event => events.push(event));
  assert.deepEqual(events, [{ type: "reply", message: "你好！" }]);
  const message: ChatMessage = { id: "reply", role: "assistant", content: "你好！", createdAt: 0, status: "done", responseType: "reply" };
  assert.equal(applyQueryError(message, new Error("network error")), message);
});

test("history restores ordinary replies without a result or error", () => {
  const messages = historyTurnToMessages({ id: "turn", query: "你好", status: "reply", created_at: "2026-10-16T10:00:00Z", response: { type: "reply", message: "你好！" } });
  assert.equal(messages[0].content, "你好");
  assert.equal(messages[1].content, "你好！");
  assert.equal(messages[1].responseType, "reply");
  assert.equal(messages[1].status, "done");
  assert.equal(messages[1].result, undefined);
  assert.equal(messages[1].error, undefined);
});
