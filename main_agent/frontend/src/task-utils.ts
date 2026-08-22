export type CreatedTask = { id: string; name: string; owner: string; status: string; agent: string };
export type BackendTask = { status: string; result?: unknown; error?: string | null };

export function createTask(name: string, agent: string, id: string): CreatedTask | null {
  const trimmedName = name.trim();
  if (!trimmedName) return null;
  return { id, name: trimmedName, owner: "You", status: "Ready to start", agent };
}

export function updateTask(task: CreatedTask, changes: Pick<CreatedTask, "owner" | "status" | "agent">): CreatedTask {
  return { ...task, ...changes };
}

export function isTaskRequest(request: string): boolean {
  return /(?:추가|등록|할당|만들)/i.test(request) && /(?:\btask\b|작업|할\s*일)/i.test(request);
}

export function getTaskAction(request: string): "chat" | "confirm" {
  return isTaskRequest(request) ? "confirm" : "chat";
}

export function createChatReply(request: string): string {
  return `Main Agent: ${request}에 대한 대화를 확인했습니다. Project Task에 추가하려면 'Task에 추가해줘'라고 말씀해 주세요.`;
}

export function shouldApplyChatResponse(selectedChat: string, responseChat: string): boolean {
  return selectedChat === responseChat;
}

export function mapTaskStatus(status: string): string {
  return ({
    queued: "Ready to start",
    running: "In Progress",
    succeeded: "Done",
    failed: "Stuck",
    cancelled: "Waiting for review",
  } as Record<string, string>)[status] ?? "Waiting for review";
}

export async function pollTask(
  taskId: string,
  fetchImpl: typeof fetch = fetch,
  intervalMs = 1000,
  maxAttempts = 30,
): Promise<BackendTask> {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const response = await fetchImpl(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (!response.ok) throw new Error(`Task polling failed (${response.status})`);
    const task = await response.json() as BackendTask;
    if (["succeeded", "failed", "cancelled"].includes(task.status)) return task;
    if (attempt < maxAttempts - 1) await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Task polling timed out");
}

export function createTaskProposal(request: string, id: string): CreatedTask | null {
  const normalized = request.toLowerCase();
  const agent = /(영상|video)/i.test(normalized)
    ? "Video Generation"
    : /(pr|개발|코드|리뷰|review)/i.test(normalized)
      ? "Development Assistant"
      : /(게임|game|q\s*&?\s*a)/i.test(normalized)
        ? "Game Q&A"
        : "Workmate AI";
  return createTask(request, agent, id);
}
