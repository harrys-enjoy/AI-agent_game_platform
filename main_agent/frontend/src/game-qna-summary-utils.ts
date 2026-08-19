export type GameQnaSummaryStatus = "pending" | "review" | "approvable" | "complete" | "attention";
export type RecentGameQnaWork = { title: string; detail: string; status: string; tone: "ready" | "review" };

export function summaryStatusLabel(status: GameQnaSummaryStatus): string {
  return { pending: "검토 대기", review: "검토 필요", approvable: "승인 가능", complete: "반영 완료", attention: "수정 필요" }[status];
}

export function storyReviewStatus(review: { status?: string; verdict?: string } | null, notice: string): GameQnaSummaryStatus {
  if (!review && !notice) return "pending";
  if (notice.includes("saved")) return "complete";
  if (review?.status === "approved" || review?.verdict === "pass") return "approvable";
  if (notice.includes("could not") || review?.status === "rejected" || review?.verdict === "reject") return "attention";
  return "review";
}

function conciseRequest(request: string): string {
  return request.replace(/^\/(?:planning|art|lore|catalog|codexbook)\s*/i, "").trim().slice(0, 60) || "요청 내용 확인";
}

export function createRecentGameQnaWork(request: string, status = "완료"): RecentGameQnaWork {
  const command = request.trim().match(/^\/([a-z-]+)/i)?.[1]?.toLowerCase();
  const title = ({ planning: "게임 기획 요청", art: "아트 프롬프트", lore: "세계관 조회", catalog: "Catalog 검색", codexbook: "도감 조회", "story-review": "스토리 검토" } as Record<string, string>)[command ?? ""] ?? "Game Q&A 질문";
  return { title, detail: conciseRequest(request), status, tone: status === "완료" ? "ready" : "review" };
}

export function upsertRecentGameQnaWork(items: RecentGameQnaWork[], work: RecentGameQnaWork): RecentGameQnaWork[] {
  return [work, ...items.filter((item) => item.title !== work.title)].slice(0, 3);
}

export function recentGameQnaWork(review: { verdict?: string } | null, notice: string, chatWork?: RecentGameQnaWork | null): RecentGameQnaWork {
  if (chatWork) return chatWork;
  if (notice.includes("saved")) return { title: "스토리 Catalog 반영", detail: "승인된 스토리가 Catalog에 저장되었습니다.", status: "완료", tone: "ready" };
  if (review) return { title: "스토리 검토", detail: "검토 결과와 핵심 요약을 확인하세요.", status: "검토 완료", tone: "review" };
  return { title: "최근 작업 없음", detail: "Game Q&A에서 요청을 보내면 여기에 표시됩니다.", status: "대기", tone: "review" };
}

export function reviewSummaryLines(review: { continuityConflicts?: string[]; timelineIssues?: string[]; characterConsistency?: string[]; factionConsistency?: string[]; missingRelationships?: string[]; suggestions?: string[] } | null): string[] {
  if (!review) return ["아직 스토리 검토 결과가 없습니다."];
  const lines = [
    ...(review.continuityConflicts ?? []).map((item) => `설정 충돌: ${item}`),
    ...(review.timelineIssues ?? []).map((item) => `타임라인: ${item}`),
    ...(review.characterConsistency ?? []).map((item) => `캐릭터: ${item}`),
    ...(review.factionConsistency ?? []).map((item) => `세력 관계: ${item}`),
    ...(review.missingRelationships ?? []).map((item) => `누락 관계: ${item}`),
    ...(review.suggestions ?? []).map((item) => `개선 제안: ${item}`),
  ];
  return lines.length ? lines.slice(0, 3) : ["주요 설정 충돌과 누락된 관계가 발견되지 않았습니다."];
}
