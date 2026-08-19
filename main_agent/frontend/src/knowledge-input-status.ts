import type { StoryReview } from "./story-review-utils";

export type KnowledgeInputState = {
  hasDraft?: boolean;
  isReviewing?: boolean;
  review?: Pick<StoryReview, "verdict"> | null;
  notice?: string;
};

export type KnowledgeInputStatus = { label: string; progress: number };

export function getKnowledgeInputStatus(state: KnowledgeInputState): KnowledgeInputStatus {
  if (state.notice?.includes("saved")) return { label: "반영 완료", progress: 100 };
  if (state.review?.verdict === "reject" || state.notice?.includes("could not")) return { label: "수정 필요", progress: 50 };
  if (state.isReviewing) return { label: "검토 중", progress: 50 };
  if (state.review?.verdict === "pass") return { label: "반영 대기", progress: 75 };
  if (state.review || state.hasDraft) return { label: "검토 결과 확인", progress: 50 };
  return { label: "업로드 대기", progress: 0 };
}
