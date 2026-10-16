/**
 * 前端应用主组件
 * 负责聊天会话状态、SSE 事件消费和整体页面布局
 */
import { Database, PanelLeft, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ConversationList } from "./components/ConversationList";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { MessageBubble } from "./components/MessageBubble";
import { streamQuery, loadConversation } from "./lib/agentApi";
import { applyQueryError } from "./lib/queryState";
import { upsertStep } from "./lib/progress";
import { summarizeResult, historyTurnToMessages } from "./lib/format";
import type { AgentEvent, ChatMessage } from "./types/agent";

const examples = [
  "统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序",
  "统计 2025 年 3 月各商品品类的销量和销售额",
  "查询华东地区 2025 年第一季度销售额最高的前 5 个商品",
  "按会员等级统计 2025 年第一季度的订单数和销售额",
];


function makeId() {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function App() {
  const [historyMutating, setHistoryMutating] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(() => {
    try { return localStorage.getItem("keeper.conversation"); } catch { return null; }
  });
  const [restoring, setRestoring] = useState(Boolean(conversationId));
  const [restoreError, setRestoreError] = useState("");
  const [historyRevision, setHistoryRevision] = useState(0);
  const [draft, setDraft] = useState("");
  const [activeController, setActiveController] = useState<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const isStreaming = Boolean(activeController);
  const busy = isStreaming || historyMutating || restoring || Boolean(restoreError);

  useEffect(() => {
    const id = conversationId;
    if (!id || !restoring) return;
    const controller = new AbortController();
    loadConversation(id, controller.signal).then(({ turns }) => {
      if (controller.signal.aborted) return;
      setMessages(turns.flatMap(historyTurnToMessages));
      setRestoring(false);
    }).catch((error: Error) => {
      if (!controller.signal.aborted) { setRestoreError(error.message); setRestoring(false); }
    });
    return () => controller.abort();
  }, [conversationId, restoring]);

  const canSubmit = draft.trim().length > 0 && !busy;

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const startQuery = async (rawQuery = draft) => {
    const query = rawQuery.trim();
    if (!query || busy) return;

    const userMessage: ChatMessage = {
      id: makeId(),
      role: "user",
      content: query,
      createdAt: Date.now(),
    };

    const assistantId = makeId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "正在连接企业数据助手...",
      createdAt: Date.now(),
      status: "streaming",
      steps: [],
    };

    const controller = new AbortController();
    setActiveController(controller);
    setDraft("");
    setMessages((current) => [...current, userMessage, assistantMessage]);

    const onEvent = (event: AgentEvent) => {
      if (event.type === "conversation") {
        setConversationId(event.conversation_id);
        setHistoryRevision(value => value + 1);
        try { localStorage.setItem("keeper.conversation", event.conversation_id); } catch { /* storage unavailable */ }
        return;
      }
      setMessages((current) =>
        current.map((message) => {
          if (message.id !== assistantId) return message;
          if (message.status !== "streaming") return message;

          if (event.type === "progress") {
            return {
              ...message,
              content: event.status === "running" ? `正在执行：${event.step}` : message.content,
              steps: upsertStep(message.steps, event),
            };
          }

          if (event.type === "artifact") {
            return { ...message, files: [...(message.files ?? []), event.file] };
          }
          if (event.type === "done") {
            return { ...message, status: event.error ? "error" : "done", content: event.message,
              results: event.results, files: event.files, error: event.error,
              responseType: event.results.length ? "result" : event.clarification ? "clarification" : "reply" };
          }
          if (event.type === "result" && event.terminal === false) {
            return { ...message, results: [...(message.results ?? []), {
              query_result_id: event.query_result_id ?? "", query: event.query ?? "", data: event.data,
            }] };
          }
          if (event.type === "clarification" || event.type === "reply") {
            return { ...message, status: "done", responseType: event.type, content: event.message };
          }
          if (event.type === "result") {
            return {
              ...message,
              status: "done",
              content: summarizeResult(event.data),
              result: event.data,
            };
          }

          return {
            ...message,
            status: "error",
            content: "这次查询没有成功。",
            error: event.message,
          };
        }),
      );
    };

    try {
      await streamQuery(query, { signal: controller.signal, onEvent, conversationId });
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? applyQueryError(message, error)
            : message,
        ),
      );
    } finally {
      setActiveController(null);
      setHistoryRevision(value => value + 1);
    }
  };

  const stopQuery = () => {
    activeController?.abort();
  };

  const selectConversation = (id: string) => {
    if (isStreaming || historyMutating || (id === conversationId && !restoreError)) return;
    setSidebarOpen(false);
    setConversationId(id);
    setMessages([]);
    setDraft("");
    setRestoreError("");
    setRestoring(true);
    try { localStorage.setItem("keeper.conversation", id); } catch { /* storage unavailable */ }
  };

  const clearConversation = () => {
    if (isStreaming) return;
    setSidebarOpen(false);
    setConversationId(null);
    setRestoring(false);
    setRestoreError("");
    try { localStorage.removeItem("keeper.conversation"); } catch { /* storage unavailable */ }
    setMessages([]);
    setDraft("");
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-white font-sans text-ink">
      {sidebarOpen && <button type="button" aria-label="关闭侧栏" onClick={() => setSidebarOpen(false)} className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[2px] md:hidden" />}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[272px] shrink-0 flex-col bg-[#f7f8fa] transition-transform duration-200 md:static md:translate-x-0 ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-20 shrink-0 items-center gap-3 px-5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-moss text-white"><Database className="h-[18px] w-[18px]" /></div>
          <div className="flex-1"><div className="text-lg font-semibold tracking-tight">Keeper</div><div className="text-[11px] text-ink/45">企业数据助手</div></div>
          <button type="button" aria-label="关闭侧栏" onClick={() => setSidebarOpen(false)} className="rounded-lg p-2 text-ink/50 hover:bg-black/5 md:hidden"><X className="h-4 w-4" /></button>
        </div>
        <div className="px-3 pb-5">
          <button type="button" onClick={clearConversation} disabled={isStreaming || historyMutating}
            className="flex w-full items-center gap-3 rounded-xl border border-black/[0.07] bg-white px-4 py-3 text-sm font-medium shadow-sm transition hover:bg-white/60 disabled:opacity-40">
            <Plus className="h-4 w-4" />新会话
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          <ConversationList selectedId={conversationId} disabled={isStreaming} revision={historyRevision} onSelect={selectConversation}
            onMutating={setHistoryMutating} onDeleted={id => { if (id === conversationId) clearConversation(); }} />
        </div>
        <div className="m-3 flex items-center gap-3 rounded-2xl border border-black/5 bg-white/70 p-3">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-moss/10 text-sm font-semibold text-moss">K</div>
          <div><p className="text-sm font-medium">我的工作空间</p><p className="mt-0.5 text-xs text-ink/40">数据洞察，从一个问题开始</p></div>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between gap-3 px-4 sm:px-7">
          <div className="flex items-center gap-2">
            <button type="button" aria-label="打开历史会话" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)} className="rounded-xl p-2 text-ink/60 hover:bg-black/5 md:hidden"><PanelLeft className="h-5 w-5" /></button>
            <span className="text-base font-medium text-ink/75">Keeper <span className="ml-1 hidden text-sm font-normal text-ink/40 sm:inline">企业数据助手</span></span>
          </div>
          <span className="flex items-center gap-2 rounded-full bg-[#f7f8fa] px-3 py-1.5 text-xs text-ink/50"><span className={`h-1.5 w-1.5 rounded-full ${isStreaming ? "animate-pulse bg-moss" : "bg-moss/60"}`} />{isStreaming ? "处理中" : "随时为你解答"}</span>
        </header>
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {restoring && <p role="status" className="mx-auto max-w-3xl px-6 py-8 text-sm text-ink/50">正在恢复会话…</p>}
          {restoreError && <p role="alert" className="mx-auto max-w-3xl rounded-2xl bg-red-50 p-4 text-sm text-red-700">{restoreError}</p>}
          {!restoring && !restoreError && (messages.length === 0 ? (
            <EmptyState examples={examples} onUseExample={(example) => setDraft(example)} />
          ) : (
            <div className="mx-auto flex w-full max-w-[860px] flex-col gap-9 px-5 py-8 sm:px-8">
              {messages.map(message => <MessageBubble key={message.id} message={message} conversationId={conversationId} />)}
            </div>
          ))}
        </div>
        <Composer value={draft} disabled={!canSubmit} isStreaming={isStreaming} onChange={setDraft} onSubmit={() => startQuery()} onStop={stopQuery} />
      </main>
    </div>
  );
}
