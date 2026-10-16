import { ArrowUpRight, Database, History, MessageSquare, Search } from "lucide-react";

type EmptyStateProps = { examples: string[]; onUseExample: (example: string) => void };
const capabilities = [
  { label: "自然语言查询", icon: Search },
  { label: "连续追问", icon: MessageSquare },
  { label: "历史会话", icon: History },
];

export function EmptyState({ examples, onUseExample }: EmptyStateProps) {
  return <div className="mx-auto flex min-h-full w-full max-w-[780px] flex-col items-center justify-center px-6 py-10 sm:py-14">
    <div className="mb-6 grid h-14 w-14 place-items-center rounded-[20px] bg-moss/10 text-moss"><Database className="h-6 w-6" strokeWidth={1.6} /></div>
    <h1 className="text-center text-3xl font-semibold tracking-tight sm:text-[36px]">今天想了解哪些数据？</h1>
    <p className="mt-4 text-center text-sm leading-6 text-ink/45 sm:text-base">用自然语言提问，让 Keeper 帮你找到答案。</p>
    <div className="mt-6 flex flex-wrap justify-center gap-2">
      {capabilities.map(({ label, icon: Icon }) => <span key={label} className="inline-flex items-center gap-1.5 rounded-full bg-[#f7f8fa] px-3 py-1.5 text-xs text-ink/50"><Icon className="h-3.5 w-3.5" />{label}</span>)}
    </div>
    <div className="mt-10 grid w-full gap-3 sm:grid-cols-2">
      {examples.map((example, index) => <button key={example} type="button" onClick={() => onUseExample(example)}
        className="group flex min-h-28 flex-col justify-between rounded-2xl border border-black/[0.07] bg-white p-4 text-left transition hover:border-moss/20 hover:bg-[#f8faf9]">
        <span className="mb-3 flex w-full items-center justify-between text-xs text-ink/40">{["区域概览", "趋势分析", "排名查询", "分组统计"][index]}<ArrowUpRight className="h-4 w-4 transition group-hover:text-moss" /></span>
        <span className="text-sm leading-6 text-ink/75">{example}</span>
      </button>)}
    </div>
  </div>;
}
