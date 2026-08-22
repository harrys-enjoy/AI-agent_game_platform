import { useRef, useState, type FormEvent } from "react";

export function ChatComposer({ disabled, onSubmit, initialValue }: { disabled: boolean; onSubmit: (message: string) => void; initialValue?: string }) {
  const [value, setValue] = useState(initialValue ?? "");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length < 5) return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 16~30초, 예산 $10 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 20초로"
          className="min-h-24 w-full rounded-[8px] border border-brief-border p-2 pr-8 text-sm text-brief-text disabled:opacity-60"
          aria-label="영상 브리프"
          disabled={disabled}
        />
        {value && !disabled && (
          <button
            type="button"
            aria-label="입력 지우기"
            title="입력 지우기"
            onClick={() => { setValue(""); textareaRef.current?.focus(); }}
            className="absolute right-2 top-2 rounded-full bg-brief-bg px-1.5 py-0.5 text-xs text-brief-muted hover:bg-brief-border"
          >
            ✕
          </button>
        )}
      </div>
      <button
        type="submit"
        disabled={disabled || value.trim().length < 5}
        className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
