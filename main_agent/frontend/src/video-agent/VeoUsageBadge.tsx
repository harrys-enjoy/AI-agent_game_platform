import { useEffect, useState } from "react";
import { getVeoUsage } from "./api";
import type { VeoUsage } from "./types";

function formatResetTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function VeoUsageBadge({ refreshKey }: { refreshKey?: unknown }) {
  const [usage, setUsage] = useState<VeoUsage | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVeoUsage()
      .then((result) => {
        if (!cancelled) setUsage(result);
      })
      .catch(() => {
        // Non-critical - just don't show the badge rather than surfacing an error banner.
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (!usage) return null;

  const atLimit = usage.used >= usage.limit;
  const near = !atLimit && usage.used >= usage.limit * 0.8;
  const colorClass = atLimit ? "border-red-300 bg-red-50 text-red-700" : near ? "border-amber-300 bg-amber-50 text-amber-700" : "border-brief-border bg-brief-bg text-brief-muted";
  const resetLabel = atLimit ? formatResetTime(usage.resetsAt) : null;

  return (
    <div
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${colorClass}`}
      title="이 앱을 통해 실제로 호출한 Veo 횟수 (Google의 실시간 남은 할당량이 아닌, 로컬 집계치입니다)"
      data-testid="veo-usage-badge"
    >
      <span>Veo 사용량: {usage.used}/{usage.limit} 오늘</span>
      {atLimit && resetLabel && <span className="opacity-80">· {resetLabel} 리셋 예상</span>}
    </div>
  );
}
