/**
 * 聊天输入区组件
 * 处理问题输入、发送和停止当前流式请求
 */
import { ArrowUp, Square, WandSparkles } from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useRef } from "react";
import { cn } from "../lib/format";

type ComposerProps = {
    value: string;
    disabled: boolean;
    isStreaming: boolean;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onStop: () => void;
};

export function Composer({
    value,
    disabled,
    isStreaming,
    onChange,
    onSubmit,
    onStop,
}: ComposerProps) {
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);

    useEffect(() => {
        const element = textareaRef.current;
        if (!element) return;
        element.style.height = "auto";
        element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
    }, [value]);

    const submit = (event: FormEvent) => {
        event.preventDefault();
        if (!disabled) onSubmit();
    };

    const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (!disabled) onSubmit();
        }
    };

    return (
        <form
            onSubmit={submit}
            className="shrink-0 bg-white px-4 pb-4 pt-3 sm:px-8"
        >
            <div className="mx-auto flex max-w-[796px] items-center gap-2 rounded-[26px] border border-black/[0.07] bg-[#f5f6f7] p-2 shadow-panel transition focus-within:border-moss/25 focus-within:bg-white">
                <div className="hidden h-10 w-9 shrink-0 place-items-center rounded-full text-ink/35 sm:grid">
                    <WandSparkles className="h-5 w-5" aria-hidden="true" />
                </div>
                <textarea
                    ref={textareaRef}
                    aria-label="输入数据查询问题"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={onKeyDown}
                    rows={1}
                    placeholder="描述你想查询的数据，或继续追问..."
                    className="max-h-40 min-h-10 min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-6 text-ink outline-none placeholder:text-ink/35"
                />
                <button
                    type={isStreaming ? "button" : "submit"}
                    onClick={isStreaming ? onStop : undefined}
                    disabled={!isStreaming && disabled}
                    className={cn(
                        "grid h-10 w-10 shrink-0 place-items-center rounded-full text-white transition focus:outline-none focus:ring-2 focus:ring-moss/40 focus:ring-offset-2",
                        isStreaming
                            ? "bg-ink hover:bg-soot"
                            : "bg-ink hover:bg-soot disabled:cursor-not-allowed disabled:bg-ink/25",
                    )}
                    title={isStreaming ? "停止" : "发送"}
                    aria-label={isStreaming ? "停止" : "发送"}
                >
                    {isStreaming ? (
                        <Square
                            className="h-4 w-4 fill-current"
                            aria-hidden="true"
                        />
                    ) : (
                        <ArrowUp className="h-5 w-5" aria-hidden="true" />
                    )}
                </button>
            </div>
            <p className="mt-3 text-center text-[11px] text-ink/35">Keeper 企业数据助手 · Enter 发送，Shift + Enter 换行</p>
        </form>
    );
}
