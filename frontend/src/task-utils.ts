export type CreatedTask = { id: string; name: string; owner: string; status: string; agent: string };

export function createTask(name: string, agent: string, id: string): CreatedTask | null {
  const trimmedName = name.trim();
  if (!trimmedName) return null;
  return { id, name: trimmedName, owner: "You", status: "Ready to start", agent };
}

export function updateTask(task: CreatedTask, changes: Pick<CreatedTask, "owner" | "status" | "agent">): CreatedTask {
  return { ...task, ...changes };
}

export function isTaskRequest(request: string): boolean {
  return /(task|작업|일정|추가해|등록해|할당해|만들어)/i.test(request);
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
