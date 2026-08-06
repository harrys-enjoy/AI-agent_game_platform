export type ChatCommand = {
  command: string;
  label: string;
  description: string;
  mode: "dev-guide" | "lore" | "catalog" | "codex";
  template: string;
};

export const commandCatalog: ChatCommand[] = [
  {
    command: "/planning",
    label: "Planning Guide",
    description: "퀘스트, 전투 시스템, 레벨 디자인, 밸런스, 규칙 설계",
    mode: "dev-guide",
    template: "게임 기획안을 작성해줘. 목표, 핵심 규칙, 진행 단계, 고려할 위험을 정리해줘.",
  },
  {
    command: "/art",
    label: "Art Guide / Video Prompt",
    description: "Video Generation 참고 프롬프트와 6개 핵심 특징 작성",
    mode: "dev-guide",
    template: "Video Generation용 참고 프롬프트를 작성해줘. 주제, 행동, 환경, 스타일, 카메라, 조명과 분위기를 정리해줘.",
  },
  {
    command: "/lore",
    label: "Lore Agent",
    description: "세계관, 인물, 세력, 사건, 관계 설정 조회",
    mode: "lore",
    template: "이 게임 세계관의 인물, 세력, 사건 관계를 정리해줘.",
  },
  {
    command: "/catalog",
    label: "Catalog",
    description: "게임 콘텐츠와 카탈로그 항목 조회",
    mode: "catalog",
    template: "게임 카탈로그에서 관련 콘텐츠를 찾아줘.",
  },
  {
    command: "/codexbook",
    label: "Codexbook / Game Codex",
    description: "캐릭터, 몬스터, 아이템 도감 조회",
    mode: "codex",
    template: "도감에서 관련 캐릭터, 몬스터, 아이템을 찾아줘.",
  },
];

export type ResolvedChatCommand =
  | { kind: "help"; commands: ChatCommand[] }
  | { kind: "request"; mode: ChatCommand["mode"]; content: string; command: string | null };

export function resolveChatCommand(input: string): ResolvedChatCommand {
  const content = input.trim();
  if (/^\/(?:\?|help)\s*$/i.test(content)) {
    return { kind: "help", commands: commandCatalog };
  }
  const match = content.match(/^\/(planning|art|lore|catalog|codexbook)(?:\s+(.*))?$/i);
  if (!match) {
    return { kind: "request", mode: "lore", content, command: null };
  }
  const command = `/${match[1].toLowerCase()}`;
  const item = commandCatalog.find((entry) => entry.command === command);
  if (!item) return { kind: "request", mode: "lore", content, command: null };
  return {
    kind: "request",
    mode: item.mode,
    content: match[2]?.trim() || item.template,
    command,
  };
}
