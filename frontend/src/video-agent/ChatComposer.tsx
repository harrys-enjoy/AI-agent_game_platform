import { useState, type FormEvent } from "react";

export function ChatComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void }) {
  const [value, setValue] = useState("");

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
        placeholder="예: 할로윈 신규 캐릭터 공개 이벤트, 15초로 만들어줘"
        className="min-h-24 rounded border border-slate-300 p-2 text-sm"
        aria-label="영상 브리프"
      />
      <button
        type="submit"
        disabled={disabled || value.trim().length < 5}
        className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
