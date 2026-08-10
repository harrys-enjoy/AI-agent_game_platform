export type StoryDraft = {
  name: string;
  keywords: string[];
  answer: string;
  relatedLoreIds: string[];
  relatedCodexIds: string[];
};

export type StoryReview = {
  reviewId: string;
  verdict: "pass" | "review_required" | "reject";
  continuityConflicts?: string[];
  timelineIssues?: string[];
  characterConsistency?: string[];
  factionConsistency?: string[];
  missingRelationships?: string[];
  suggestions?: string[];
  evidence?: string[];
  approvalRequired: boolean;
};

export function buildStoryDraft(name: string, keywords: string, answer: string): StoryDraft {
  return {
    name: name.trim(),
    keywords: keywords.split(",").map((item) => item.trim()).filter(Boolean),
    answer: answer.trim(),
    relatedLoreIds: [],
    relatedCodexIds: [],
  };
}

export function canApproveStory(review: StoryReview | null): boolean {
  return review?.verdict === "pass" && review.approvalRequired === false;
}

export function reviewLabel(review: StoryReview | null): string {
  if (review?.verdict === "pass") return "Ready for approval";
  if (review?.verdict === "reject") return "Rejected";
  return "Review required";
}
