import { useEffect, useState } from "react";
import { History, Trash2 } from "lucide-react";
import { changeConversationDeleted, listConversations, type ConversationSummary } from "../lib/agentApi";
import { cn } from "../lib/format";

type Props = {
  selectedId: string | null;
  disabled: boolean;
  revision: number;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
  onMutating: (busy: boolean) => void;
};

export function ConversationList({ selectedId, disabled, revision, onSelect, onDeleted, onMutating }: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletedItem, setDeletedItem] = useState<ConversationSummary | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  // 查询完成时重新读取首页，按最新更新时间排序。
  const [seenRevision, setSeenRevision] = useState(revision);
  if (seenRevision !== revision) {
    setSeenRevision(revision);
    setOffset(0);
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    listConversations(offset, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setItems(current => offset === 0 ? page.items : [...new Map([...current, ...page.items].map(item => [item.id, item])).values()]);
      setHasMore(page.has_more);
      setLoading(false);
    }).catch((reason: Error) => {
      if (controller.signal.aborted) return;
      setError(reason.message);
      setLoading(false);
    });
    return () => controller.abort();
  }, [offset, revision, retry]);

  const changeDeleted = async (item: ConversationSummary, deleted: boolean) => {
    if (disabled || mutating) return;
    setMutating(true);
    onMutating(true);
    setMutationError("");
    try {
      await changeConversationDeleted(item.id, deleted);
      setConfirmId(null);
      setDeletedItem(deleted ? item : null);
      if (deleted) {
        setItems(current => current.filter(value => value.id !== item.id));
        onDeleted(item.id);
      }
      setOffset(0);
      setRetry(value => value + 1);
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason.message : "操作失败，请重试。");
    } finally {
      setMutating(false);
      onMutating(false);
    }
  };

  return <section aria-label="历史会话">
    <div className="mb-2 flex items-center gap-2 px-3 text-[11px] font-medium text-ink/45">
      <History className="h-3.5 w-3.5" aria-hidden="true" />历史会话
    </div>
    <div className="space-y-1">
      {items.map(item => <div key={item.id} className={cn("group rounded-xl transition", selectedId === item.id ? "bg-[#e5ebe8]" : "hover:bg-black/[0.04]")}>
        <div className="flex items-center">
          <button type="button" disabled={disabled || mutating} onClick={() => onSelect(item.id)}
            aria-current={selectedId === item.id ? "page" : undefined} title={item.title}
            className="min-w-0 flex-1 rounded-xl px-3 py-3 text-left disabled:opacity-55">
            <div className="truncate text-sm leading-5 text-ink/80">{item.title}</div>
            <div className="mt-1 text-xs text-ink/45">{new Date(item.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</div>
          </button>
          <button type="button" disabled={disabled || mutating} aria-label={`删除会话：${item.title}`} title="删除会话"
            onClick={() => { setConfirmId(item.id); setMutationError(""); }}
            className="mr-2 rounded-lg p-2 text-ink/35 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-30">
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
        {confirmId === item.id && <div className="px-3 pb-3 text-xs">
          <p className="mb-2 text-ink/60">删除这条会话？删除后可撤销。</p>
          <div className="flex gap-2">
            <button type="button" disabled={disabled || mutating} onClick={() => changeDeleted(item, true)} className="rounded-lg bg-red-50 px-3 py-1.5 text-red-700 disabled:opacity-40">{mutating ? "处理中…" : "确认删除"}</button>
            <button type="button" disabled={mutating} onClick={() => setConfirmId(null)} className="rounded-lg bg-white px-3 py-1.5 text-ink/60">取消</button>
          </div>
        </div>}
      </div>)}
      {mutationError && <p role="alert" className="px-2 py-2 text-xs text-red-700">{mutationError}</p>}
      {deletedItem && <div role="status" className="rounded-xl bg-white p-3 text-xs text-ink/60">已删除会话
        <button type="button" disabled={disabled || mutating} onClick={() => changeDeleted(deletedItem, false)} className="ml-3 text-moss underline disabled:opacity-40">撤销</button>
      </div>}
      {loading && <p role="status" className="px-1 text-xs text-ink/50">正在加载…</p>}
      {!loading && !error && items.length === 0 && <p className="px-1 text-xs text-ink/50">暂无历史会话，发送问题后自动保存。</p>}
      {error && <div role="alert" className="text-xs text-tomato">{error}<button type="button" className="ml-2 underline" onClick={() => setRetry(value => value + 1)}>重试</button></div>}
      {hasMore && !error && <button type="button" disabled={loading || disabled} onClick={() => setOffset(value => value + 30)} className="w-full rounded-xl py-2 text-xs text-ink/60 disabled:opacity-40">加载更多</button>}
    </div>
  </section>;
}
