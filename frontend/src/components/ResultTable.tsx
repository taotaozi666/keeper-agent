/**
 * 查询结果表格组件
 * 将后端返回的结构化数据归一化为可滚动表格
 */
import { Database, FileJson } from "lucide-react";

function normalizeRows(data: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(data)) {
    return data.map((item, index) =>
      item && typeof item === "object" && !Array.isArray(item)
        ? (item as Record<string, unknown>)
        : { 序号: index + 1, 值: item },
    );
  }

  if (data && typeof data === "object") {
    return [data as Record<string, unknown>];
  }

  return [{ 值: data ?? "" }];
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ResultTable({ data }: { data: unknown }) {
  const rows = normalizeRows(data);
  if (rows.length === 0) {
    return (
      <section role="status" className="mt-4 rounded-2xl border border-ink/10 bg-white/70 px-4 py-4 text-sm text-ink/65 shadow-line">
        <div className="flex items-center gap-2 font-semibold">
          <Database className="h-4 w-4 text-moss" aria-hidden="true" />
          查询结果 · 0 行
        </div>
        <p className="mt-2">没有符合当前筛选条件的数据，可以调整时间范围或筛选条件后重试。</p>
      </section>
    );
  }
  const columns = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set<string>()),
  );

  if (columns.length === 0) {
    return null;
  }

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-ink/10 bg-white/70 shadow-line">
      <div className="flex items-center justify-between border-b border-ink/10 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Database className="h-4 w-4 text-moss" aria-hidden="true" />
          查询结果
        </div>
        <div className="flex items-center gap-2 text-xs text-ink/55">
          <FileJson className="h-3.5 w-3.5" aria-hidden="true" />
          {rows.length} 行
        </div>
      </div>
      <div className="max-h-[360px] overflow-auto">
        <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
          <thead className="sticky top-0 z-10 bg-[#f5f6f7]">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="border-b border-ink/10 px-4 py-3 font-semibold text-ink/70"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="bg-white transition hover:bg-[#f8faf9]">
                {columns.map((column) => (
                  <td key={column} className="border-b border-ink/5 px-4 py-3 text-ink/80 break-words max-w-[400px]">
                    {formatCell(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
