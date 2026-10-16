import { useState } from "react";
import { Download, FileSpreadsheet, LoaderCircle } from "lucide-react";
import type { DownloadFile } from "../types/agent";
import { downloadArtifact } from "../lib/agentApi";

export function FileCard({ file, conversationId }: { file: DownloadFile; conversationId: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const expired = Date.parse(file.expires_at) <= Date.now();
  const download = async () => {
    setLoading(true); setError("");
    try { await downloadArtifact(conversationId, file.id, file.name); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "下载失败，请重试"); }
    finally { setLoading(false); }
  };
  return <div className="mt-4 rounded-2xl border border-ink/10 bg-white p-4">
    <div className="flex items-center gap-3">
      <FileSpreadsheet className="h-6 w-6 shrink-0 text-moss" aria-hidden="true" />
      <div className="min-w-0 flex-1"><p className="break-all text-sm font-medium">{file.name}</p>
        <p className="mt-1 text-xs text-ink/50">{file.row_count} 行 · {(file.size / 1024).toFixed(1)} KB · {expired ? "文件已过期，请重新导出" : `有效至 ${new Date(file.expires_at).toLocaleString("zh-CN")}`}</p></div>
      <button type="button" aria-label={`下载 ${file.name}`} disabled={loading || expired} onClick={download}
        className="rounded-xl bg-moss/10 p-2.5 text-moss hover:bg-moss/20 disabled:opacity-40">
        {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
      </button>
    </div>
    {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
  </div>;
}
