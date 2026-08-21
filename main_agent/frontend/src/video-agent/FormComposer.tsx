import { useRef, useState, type FormEvent } from "react";
import { composeStructuredBrief } from "./brief-compose";

const INTEGER_PATTERN = /^\d*$/;
const DECIMAL_PATTERN = /^\d*\.?\d*$/;
const MAX_DURATION_SEC = 30;
const MAX_BUDGET_USD = 10;

function toFiniteNumber(value: string): number | undefined {
  const parsed = Number(value);
  return value !== "" && Number.isFinite(parsed) ? parsed : undefined;
}

export function FormComposer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (message: string) => void }) {
  const [brief, setBrief] = useState("");
  const [durationSec, setDurationSec] = useState("");
  const [preset, setPreset] = useState("");
  const [sceneType, setSceneType] = useState("");
  const [maxBudgetUsd, setMaxBudgetUsd] = useState("");
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const durationRef = useRef<HTMLInputElement>(null);
  const budgetRef = useRef<HTMLInputElement>(null);
  const durationValue = toFiniteNumber(durationSec);
  const durationTooLong = durationValue !== undefined && durationValue > MAX_DURATION_SEC;
  const budgetValue = toFiniteNumber(maxBudgetUsd);
  const budgetOverCap = budgetValue !== undefined && budgetValue > MAX_BUDGET_USD;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (brief.trim().length < 5 || durationTooLong) return;
    const message = composeStructuredBrief({
      brief,
      durationSec: toFiniteNumber(durationSec),
      preset: preset ? (preset as "이벤트" | "공개" | "커뮤니티") : undefined,
      sceneType: sceneType ? (sceneType as "인게임" | "스튜디오") : undefined,
      maxBudgetUsd: toFiniteNumber(maxBudgetUsd),
    });
    onSubmit(message);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="relative">
        <textarea
          ref={briefRef}
          value={brief}
          onChange={(event) => setBrief(event.target.value)}
          placeholder="브리프 (필수)"
          aria-label="브리프"
          className="min-h-16 w-full rounded-[8px] border border-brief-border p-2 pr-8 text-sm text-brief-text disabled:opacity-60"
          disabled={disabled}
        />
        {brief && !disabled && (
          <button
            type="button"
            aria-label="브리프 지우기"
            title="입력 지우기"
            onClick={() => { setBrief(""); briefRef.current?.focus(); }}
            className="absolute right-2 top-2 rounded-full bg-brief-bg px-1.5 py-0.5 text-xs text-brief-muted hover:bg-brief-border"
          >
            ✕
          </button>
        )}
      </div>
      <div className="relative">
        <input
          ref={durationRef}
          value={durationSec}
          onChange={(event) => { if (INTEGER_PATTERN.test(event.target.value)) setDurationSec(event.target.value); }}
          placeholder="길이(초)"
          aria-label="길이(초)"
          inputMode="numeric"
          className="w-full rounded-[8px] border border-brief-border p-2 pr-8 text-sm text-brief-text disabled:opacity-60"
          disabled={disabled}
        />
        {durationSec && !disabled && (
          <button
            type="button"
            aria-label="길이(초) 지우기"
            title="입력 지우기"
            onClick={() => { setDurationSec(""); durationRef.current?.focus(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-brief-bg px-1.5 py-0.5 text-xs text-brief-muted hover:bg-brief-border"
          >
            ✕
          </button>
        )}
      </div>
      {durationTooLong && (
        <p className="-mt-1 text-xs text-red-600" data-testid="duration-cap-warning">
          영상 길이는 {MAX_DURATION_SEC}초를 넘을 수 없습니다.
        </p>
      )}
      <select
        value={preset}
        onChange={(event) => setPreset(event.target.value)}
        aria-label="프리셋"
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text disabled:opacity-60"
        disabled={disabled}
      >
        <option value="">프리셋 선택 안 함</option>
        <option value="이벤트">이벤트</option>
        <option value="공개">공개</option>
        <option value="커뮤니티">커뮤니티</option>
      </select>
      <select
        value={sceneType}
        onChange={(event) => setSceneType(event.target.value)}
        aria-label="씬 종류"
        className="rounded-[8px] border border-brief-border p-2 text-sm text-brief-text disabled:opacity-60"
        disabled={disabled}
      >
        <option value="">씬 종류 선택 안 함</option>
        <option value="인게임">인게임</option>
        <option value="스튜디오">스튜디오</option>
      </select>
      <div className="relative">
        <input
          ref={budgetRef}
          value={maxBudgetUsd}
          onChange={(event) => { if (DECIMAL_PATTERN.test(event.target.value)) setMaxBudgetUsd(event.target.value); }}
          placeholder="예산(달러)"
          aria-label="예산(달러)"
          inputMode="decimal"
          className="w-full rounded-[8px] border border-brief-border p-2 pr-8 text-sm text-brief-text disabled:opacity-60"
          disabled={disabled}
        />
        {maxBudgetUsd && !disabled && (
          <button
            type="button"
            aria-label="예산(달러) 지우기"
            title="입력 지우기"
            onClick={() => { setMaxBudgetUsd(""); budgetRef.current?.focus(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-brief-bg px-1.5 py-0.5 text-xs text-brief-muted hover:bg-brief-border"
          >
            ✕
          </button>
        )}
      </div>
      {budgetOverCap && (
        <p className="-mt-1 text-xs text-amber-600" data-testid="budget-cap-warning">
          예산은 최대 ${MAX_BUDGET_USD}까지만 지원되어 자동으로 ${MAX_BUDGET_USD}로 제한됩니다.
        </p>
      )}
      <button
        type="submit"
        disabled={disabled || brief.trim().length < 5 || durationTooLong}
        className="rounded-[8px] bg-brief-accent px-3 py-2 text-sm text-white disabled:opacity-40"
      >
        생성 요청
      </button>
    </form>
  );
}
