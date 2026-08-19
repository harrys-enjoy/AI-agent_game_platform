import { AppError } from './errors.js';

const planningKeywords = ['기획', '퀘스트', '전투 시스템', '레벨 디자인', '밸런스', '규칙', '스킬 설계'];

function selectDevGuideAgent(question) {
  return planningKeywords.some((keyword) => question.includes(keyword))
    ? 'planning-guide'
    : 'art-guide';
}

function cacheKey(request) {
  const context = request.context ?? {};
  return JSON.stringify([
    request.mode,
    request.question,
    context.projectId ?? '',
    context.userId ?? '',
    context.contextId ?? '',
    context.workContext ?? '',
    request.evidence ?? [],
  ]);
}

export function createOrchestrator({ agents, lookup, cacheTtlMs = 60_000, cacheMaxEntries = 100 }) {
  const cache = new Map();
  const metrics = { cacheHits: 0, directKnowledgeResponses: 0, agentCalls: 0 };

  function readCache(request) {
    if (cacheTtlMs <= 0) return null;
    const entry = cache.get(cacheKey(request));
    if (!entry) return null;
    if (entry.expiresAt <= Date.now()) {
      cache.delete(cacheKey(request));
      return null;
    }
    metrics.cacheHits += 1;
    return { ...entry.response, requestId: request.requestId };
  }

  function writeCache(request, response) {
    if (cacheTtlMs <= 0) return;
    const key = cacheKey(request);
    cache.set(key, { expiresAt: Date.now() + cacheTtlMs, response: { ...response, requestId: undefined } });
    while (cache.size > cacheMaxEntries) cache.delete(cache.keys().next().value);
  }

  return {
    async ask(request) {
      const cached = readCache(request);
      if (cached) return cached;

      const direct = lookup(request.mode, request.question);
      if (direct) {
        metrics.directKnowledgeResponses += 1;
        const response = {
          answer: direct.answer,
          mode: request.mode,
          agent: 'knowledge',
          sources: direct.sources,
          usage: null,
          requestId: request.requestId,
        };
        writeCache(request, response);
        return response;
      }

      if (request.mode === 'catalog' || request.mode === 'codex') {
        throw new AppError('KNOWLEDGE_NOT_FOUND', '요청과 일치하는 게임 자료를 찾지 못했습니다.', 404);
      }

      const agentName = request.mode === 'dev-guide'
        ? selectDevGuideAgent(request.question)
        : 'lore';
      const agent = agents.get(agentName);
      if (!agent) {
        throw new AppError('INTERNAL_ERROR', `에이전트를 사용할 수 없습니다: ${agentName}`, 500);
      }
      metrics.agentCalls += 1;
      const result = await agent.ask({ ...request, evidence: request.evidence ?? [] });
      const response = {
        answer: result.answer,
        mode: request.mode,
        agent: result.agent,
        sources: result.sources,
        usage: result.usage ?? null,
        requestId: request.requestId,
      };
      writeCache(request, response);
      return response;
    },
    getMetrics() {
      return { ...metrics };
    },
  };
}
