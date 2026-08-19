export type ChatScrollElement = { scrollTop: number; scrollHeight: number };

export function scrollChatToBottom(element: ChatScrollElement | null | undefined): void {
  if (!element) return;
  element.scrollTop = element.scrollHeight;
}
