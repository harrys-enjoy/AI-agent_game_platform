const agentPrompts = {
  'planning-guide': '게임 기획 가이드로 답한다. 근거가 없으면 추측하지 않는다.',
  'art-guide': '게임 아트 가이드로 답한다. 근거가 없으면 추측하지 않는다.',
  lore: '게임 세계관 가이드로 답한다. 근거가 없으면 추측하지 않는다.',
};

function createAgent(name, modelAdapter) {
  return {
    async ask({ question, evidence = [] }) {
      const result = await modelAdapter.generate({
        system: agentPrompts[name],
        question,
        evidence: evidence.slice(0, 5),
        maxOutputChars: 800,
      });
      return {
        answer: result.answer,
        agent: name,
        sources: evidence.slice(0, 5),
        usage: result.usage ?? null,
        confidence: null,
      };
    },
  };
}

export function createAgentRegistry({ modelAdapter }) {
  return new Map(Object.keys(agentPrompts).map((name) => [name, createAgent(name, modelAdapter)]));
}
