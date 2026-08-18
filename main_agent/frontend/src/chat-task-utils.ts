export type AgentWorkTask = {
  id: string;
  chat: string;
  title: string;
  status: "working" | "done" | "error";
  hidden: boolean;
};

export function normalizeAgentWorkTasks(items: AgentWorkTask[]): AgentWorkTask[] {
  return items.filter((item) => !(item.chat === "Game Q&A" && item.title === "스토리 검토"));
}

export function syncGameQnaStoryReviewTask(
  items: AgentWorkTask[],
  status: AgentWorkTask["status"],
  id: string,
): AgentWorkTask[] {
  const withoutStoryReview = items.filter((item) => !(item.chat === "Game Q&A" && item.title === "스토리 검토"));
  const existing = withoutStoryReview.find((item) => item.chat === "Game Q&A");
  if (existing) return withoutStoryReview.map((item) => item.id === existing.id ? { ...item, status, hidden: false } : item);
  return [...withoutStoryReview, { id, chat: "Game Q&A", title: "Game Q&A 작업", status, hidden: false }];
}
