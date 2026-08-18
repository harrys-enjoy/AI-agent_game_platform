const skills = [
  ['dev-guide', '게임 기획·아트 가이드 Q&A'],
  ['catalog', '게임 카탈로그 조회'],
  ['codex', '캐릭터·몬스터·아이템 도감 조회'],
  ['lore', '게임 세계관 Q&A'],
];

export function createAgentCard({ publicUrl = 'http://localhost:3000', requiresAuth = false } = {}) {
  const baseUrl = publicUrl.replace(/\/$/, '');
  const card = {
    name: 'game-qna-agent',
    description: '게임 기획·아트 가이드 및 게임 콘텐츠 Q&A 전문 에이전트',
    url: `${baseUrl}/message:send`,
    version: '0.1.0',
    supportedInterfaces: [{
      url: `${baseUrl}/message:send`,
      protocolBinding: 'HTTP+JSON',
      protocolVersion: '1.0',
    }],
    capabilities: { streaming: false, pushNotifications: false },
    defaultInputModes: ['application/json'],
    defaultOutputModes: ['application/json'],
    skills: skills.map(([id, description]) => ({
      id,
      name: id,
      description,
      inputModes: ['application/json'],
      outputModes: ['application/json'],
    })),
  };
  if (requiresAuth) {
    card.securitySchemes = {
      bearerAuth: { type: 'http', scheme: 'bearer' },
    };
  }
  return card;
}
