/**
 * 智能体执行流程图组件
 * 按 LangGraph 节点拓扑展示各步骤状态
 */
import { Check, Circle, LoaderCircle, X } from "lucide-react";
import { cn } from "../lib/format";
import type { ProgressStatus, StepState } from "../types/agent";

type FlowStatus = ProgressStatus | "pending";

type FlowNode = {
  step: string;
  x: number;
  y: number;
  w?: number;
};

const nodes: FlowNode[] = [
  { step: "抽取关键词", x: 410, y: 20 },
  { step: "统一扩展检索词", x: 410, y: 100, w: 190 },
  { step: "批量向量化检索词", x: 330, y: 190, w: 210 },
  { step: "召回字段信息", x: 150, y: 280 },
  { step: "召回指标信息", x: 410, y: 280 },
  { step: "召回字段取值", x: 670, y: 280 },
  { step: "合并召回信息", x: 410, y: 380 },
  { step: "联合筛选表字段与指标", x: 410, y: 470, w: 230 },
  { step: "添加额外上下文", x: 410, y: 560, w: 190 },
  { step: "生成SQL", x: 410, y: 650 },
  { step: "校验SQL", x: 410, y: 740 },
  { step: "校正SQL", x: 670, y: 740 },
  { step: "执行SQL", x: 410, y: 840 },
];

const connectors = [
  "M410 60 L410 94",
  "M410 140 L410 164 L330 164 L330 184",
  "M410 140 L410 164 L670 164 L670 274",
  "M330 230 L330 250 L150 250 L150 274",
  "M330 230 L330 250 L410 250 L410 274",
  "M150 320 L150 350 L410 350 L410 374",
  "M410 320 L410 374",
  "M670 320 L670 350 L410 350 L410 374",
  "M410 420 L410 464",
  "M410 510 L410 554",
  "M410 600 L410 644",
  "M410 690 L410 734",
  "M410 780 L410 834",
  "M488 760 L586 760",
  "M670 780 L670 806 L510 806 L510 772 L494 772",
];

const branchLabels = [
  { text: "有误且未达上限", x: 500, y: 730 },
  { text: "通过", x: 366, y: 815 },
  { text: "重新校验 · 最多修复 2 次", x: 540, y: 830 },
];

function getStatusMap(steps: StepState[]) {
  return steps.reduce<Record<string, StepState>>((map, item) => {
    map[item.step] = item;
    return map;
  }, {});
}

function statusFor(step: string, map: Record<string, StepState>): FlowStatus {
  return map[step]?.status ?? "pending";
}

function NodeIcon({ status }: { status: FlowStatus }) {
  if (status === "running") {
    return <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />;
  }

  if (status === "success") {
    return <Check className="h-3.5 w-3.5" aria-hidden="true" />;
  }

  if (status === "error") {
    return <X className="h-3.5 w-3.5" aria-hidden="true" />;
  }

  return <Circle className="h-3.5 w-3.5" aria-hidden="true" />;
}

function FlowNodeCard({ node, status }: { node: FlowNode; status: FlowStatus }) {
  const width = node.w ?? 156;

  return (
    <div
      className="absolute -translate-x-1/2"
      style={{ left: node.x, top: node.y, width }}
    >
      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-xl border px-3 text-sm font-semibold shadow-line transition",
          status === "pending" && "border-ink/10 bg-white/55 text-ink/45",
          status === "running" && "border-brass/45 bg-brass/15 text-ink",
          status === "success" && "border-moss/25 bg-moss/10 text-ink",
          status === "error" && "border-tomato/35 bg-tomato/10 text-tomato",
        )}
      >
        <span
          className={cn(
            "grid h-6 w-6 shrink-0 place-items-center rounded-full",
            status === "pending" && "bg-ink/5 text-ink/35",
            status === "running" && "bg-brass/20 text-brass",
            status === "success" && "bg-moss/15 text-moss",
            status === "error" && "bg-tomato/15 text-tomato",
          )}
        >
          <NodeIcon status={status} />
        </span>
        <span className="min-w-0 flex-1 truncate">{node.step}</span>
      </div>
    </div>
  );
}

export function StepRail({ steps = [] }: { steps?: StepState[] }) {
  if (steps.length === 0) return null;

  const toolSteps = steps.filter(item => !/^查询 \d+ · /.test(item.step));
  const groups = new Map<string, StepState[]>();
  for (const item of steps) {
    const match = item.step.match(/^(查询 \d+) · (.*)$/);
    if (match) groups.set(match[1], [...(groups.get(match[1]) ?? []), { ...item, step: match[2] }]);
  }
  if (groups.size || steps.some(item => item.step === "任务规划" || item.step.startsWith("工具 "))) {
    return <div className="mt-4 space-y-3">
      <div className="flex flex-wrap gap-2">{toolSteps.map(item => <div key={item.step} className="flex items-center gap-2 rounded-xl bg-white/70 px-3 py-2 text-xs">
        <NodeIcon status={item.status} /><span>{item.step}</span>
      </div>)}</div>
      {[...groups].map(([label, items]) => <div key={label}><p className="text-xs text-ink/55">{label}</p><StepRail steps={items} /></div>)}
    </div>;
  }

  const statusMap = getStatusMap(steps);

  return (
    <section className="mt-4 rounded-2xl border border-ink/10 bg-white/40 px-3 py-4 shadow-line">
      <div className="mb-3 flex items-center justify-between gap-3 px-1">
        <div className="text-sm font-semibold text-ink">执行流程</div>
        <div className="text-xs text-ink/45">LangGraph · 达到修复上限后终止</div>
      </div>

      <div className="overflow-x-auto">
        <div className="relative mx-auto h-[900px] w-[820px]">
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox="0 0 820 900"
            fill="none"
            aria-hidden="true"
          >
            <defs>
              <marker
                id="flow-arrow"
                markerHeight="8"
                markerWidth="8"
                orient="auto"
                refX="6"
                refY="4"
              >
                <path d="M0 0 L8 4 L0 8 Z" fill="rgba(32,32,29,0.58)" />
              </marker>
            </defs>
            {connectors.map((path) => (
              <path
                key={path}
                d={path}
                stroke="rgba(32,32,29,0.5)"
                strokeWidth="1.5"
                markerEnd="url(#flow-arrow)"
              />
            ))}
            {branchLabels.map((label) => (
              <text
                key={label.text}
                x={label.x}
                y={label.y}
                fill="rgba(32,32,29,0.62)"
                fontSize="13"
                fontWeight="600"
              >
                {label.text}
              </text>
            ))}
          </svg>

          {nodes.map((node) => (
            <FlowNodeCard
              key={node.step}
              node={node}
              status={statusFor(node.step, statusMap)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
