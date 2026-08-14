import { useState, type FormEvent } from "react";

export function ChatComposer({ disabled, onSubmit, initialValue }: { disabled: boolean; onSubmit: (message: string) => void; initialValue?: string }) {
  const [value, setValue] = useState(initialValue ?? "");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length < 5) return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="무엇을 홍보할지 구체적으로 적어주세요 (캐릭터/이벤트/게임 장면 등, 30초 이하, 예산 $5 이하). 예: 할로윈 신규 캐릭터 '루멘' 공개 이벤트, 15초로"
        className="min-h-24 rounded-[8px] border border-brief-border p-2 text-sm text-brief-text"
        aria-label="영상 브리프"
      />
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
