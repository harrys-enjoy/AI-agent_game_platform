import { AppError } from './errors.js';

const planningKeywords = ['기획', '퀘스트', '전투 시스템', '레벨 디자인', '밸런스', '규칙', '스킬 설계'];

function isVideoPromptRequest(question) {
  return /^(?:\/art|\/\?\s*video)(?:\s|$)/i.test(question.trim());
}

function selectDevGuideAgent(question) {
  if (isVideoPromptRequest(question)) return 'video-prompt-guide';
  return planningKeywords.some((keyword) => question.includes(keyword))
    ? 'planning-guide'
    : 'art-guide';
}

function sourceLabel(mode) {
  return {
    'dev-guide': 'Source: Guide (planning / art)',
    lore: 'Source: World Lore',
    catalog: 'Source: Catalog (game content)',
    codex: 'Source: Codex (characters / monsters / items)',
  }[mode] ?? 'Source: Game Q&A';
}

function withSourceLabel(answer, mode) {
  return `[${sourceLabel(mode)}]\n${answer}`;
}

function cacheKey(request) {
  const context = request.context ?? {};
  return JSON.stringify([
    request.mode,
    request.locale ?? 'ko',
    request.question,
    context.projectId ?? '',
    context.userId ?? '',
    context.contextId ?? '',
    context.workContext ?? '',
    request.evidence ?? [],
  ]);
}

export function createOrchestrator({ agents, lookup, lookupBest = null, listKnowledge = null, cacheTtlMs = 60_000, cacheMaxEntries = 100 }) {
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

      const direct = request.mode === 'dev-guide' && isVideoPromptRequest(request.question)
        ? null
        : request.mode === 'lore' && typeof lookupBest === 'function'
        ? lookupBest(request.question, request.locale ?? 'ko')
        : lookup(request.mode, request.question, request.locale ?? 'ko');
      if (direct) {
        const directMode = direct.mode ?? request.mode;
        metrics.directKnowledgeResponses += 1;
        const response = {
          answer: withSourceLabel(direct.answer, directMode),
          mode: directMode,
          agent: 'knowledge',
          sources: direct.sources,
          usage: null,
          requestId: request.requestId,
        };
        writeCache(request, response);
        return response;
      }

      if (request.mode === 'lore' && typeof listKnowledge === 'function') {
        for (const fallbackMode of ['catalog', 'codex']) {
          const fallback = lookup(fallbackMode, request.question, request.locale ?? 'ko');
          if (fallback) {
            metrics.directKnowledgeResponses += 1;
            const response = {
              answer: withSourceLabel(fallback.answer, fallbackMode),
              mode: fallbackMode,
              agent: 'knowledge',
              sources: fallback.sources,
              usage: null,
              requestId: request.requestId,
            };
            writeCache(request, response);
            return response;
          }
        }
      }

      if (request.mode === 'catalog' || request.mode === 'codex') {
        if (typeof listKnowledge === 'function') {
          const entries = listKnowledge(request.mode, { full: false, locale: request.locale ?? 'ko' }).slice(0, 12);
          return {
            answer: entries.length > 0
              ? `${request.mode === 'codex' ? '도감' : '카탈로그'}에서 현재 확인 가능한 항목입니다.\n\n${entries.map((entry) => `- ${entry.name}: ${entry.keywords.join(', ')}`).join('\n')}`
              : '현재 등록된 게임 자료가 없습니다.',
            mode: request.mode,
            agent: 'knowledge',
            sources: entries.map((entry) => `${request.mode}:${entry.id}`),
            usage: null,
            requestId: request.requestId,
          };
        }
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
      const videoPrompt = request.mode === 'dev-guide' && isVideoPromptRequest(request.question);
      const promptTopic = request.question.replace(/^(?:\/art|\/\?\s*video)\s*/i, '').trim();
      const characterKnowledge = videoPrompt && typeof lookupBest === 'function'
        ? lookupBest(promptTopic, request.locale ?? 'ko')
        : null;
      const evidence = [
        ...(request.evidence ?? []),
        ...(characterKnowledge?.answer ? [`스토리·인물 설정 근거:\n${characterKnowledge.answer}`] : []),
      ];
      const result = await agent.ask({ ...request, evidence });
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
