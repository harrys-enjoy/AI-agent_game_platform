export const agentNames = ["Workmate AI", "Video Generation", "Development Assistant", "Game Q&A"] as const;
export type AgentName = (typeof agentNames)[number];

export function routeAgentRequest(request: string): AgentName | null {
  const text = request.toLowerCase();
  if (/영상|비디오|동영상|렌더|편집|자막|video|render|edit|motion/.test(text)) return "Video Generation";
  if (/개발|코드|버그|오류|api|배포|프론트|백엔드|development|code|bug|debug/.test(text)) return "Development Assistant";
  if (/게임|스토리|캐릭터|퀘스트|세계관|q&a|game|story|character|quest/.test(text)) return "Game Q&A";
  if (/업무|할 일|회의|프로젝트|마감|정책|workmate|task|meeting|project/.test(text)) return "Workmate AI";
  return null;
}
