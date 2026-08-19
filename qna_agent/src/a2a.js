import { AppError } from './errors.js';

export function createAgentRequest({ requestId, mode, question, context = {}, evidence = [] }) {
  return { requestId, mode, question, context, evidence };
}

function normalizeAgentResponse(payload, agentName) {
  if (!payload || typeof payload.answer !== 'string') {
    throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트 응답 형식이 올바르지 않습니다.', 503);
  }
  return {
    answer: payload.answer,
    agent: agentName,
    sources: Array.isArray(payload.sources) ? payload.sources : [],
    usage: payload.usage ?? null,
    confidence: Number.isFinite(payload.confidence) ? payload.confidence : null,
  };
}

function readTextParts(parts) {
  if (!Array.isArray(parts)) return '';
  return parts
    .filter((part) => typeof part?.text === 'string')
    .map((part) => part.text)
    .join('\n');
}

function readA2AAnswer(payload) {
  const artifactAnswer = Array.isArray(payload?.task?.artifacts)
    ? payload.task.artifacts.map((artifact) => readTextParts(artifact.parts)).find(Boolean)
    : '';
  return readTextParts(payload?.message?.parts)
    || readTextParts(payload?.task?.status?.message?.parts)
    || artifactAnswer
    || '';
}

export function createHttpAgent({ agentName, endpoint, headers = {}, timeoutMs = 5000, fetchImpl = fetch }) {
  if (!agentName || !endpoint) throw new TypeError('agentName과 endpoint가 필요합니다.');
  return {
    async ask(input) {
      let response;
      try {
        response = await fetchImpl(endpoint, {
          method: 'POST',
          headers: { 'content-type': 'application/json', ...headers },
          signal: AbortSignal.timeout(timeoutMs),
          body: JSON.stringify(createAgentRequest(input)),
        });
      } catch {
        throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트에 연결할 수 없습니다.', 503);
      }
      if (!response.ok) {
        throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트가 요청을 처리하지 못했습니다.', 503);
      }
      try {
        return normalizeAgentResponse(await response.json(), agentName);
      } catch (error) {
        if (error instanceof AppError) throw error;
        throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트 응답을 읽지 못했습니다.', 503);
      }
    },
  };
}

export function createHttpJsonAgent({ agentName, endpoint, headers = {}, timeoutMs = 5000, fetchImpl = fetch }) {
  if (!agentName || !endpoint) throw new TypeError('agentName과 endpoint가 필요합니다.');
  return {
    async ask(input) {
      let response;
      try {
        response = await fetchImpl(endpoint, {
          method: 'POST',
          headers: { 'content-type': 'application/a2a+json', ...headers },
          signal: AbortSignal.timeout(timeoutMs),
          body: JSON.stringify({
            message: {
              messageId: input.requestId,
              role: 'ROLE_USER',
              parts: [{ text: input.question }],
              ...(input.context?.contextId ? { contextId: input.context.contextId } : {}),
            },
            metadata: { mode: input.mode, context: input.context, evidence: input.evidence },
          }),
        });
      } catch {
        throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트에 연결할 수 없습니다.', 503);
      }
      if (!response.ok) {
        throw new AppError('MODEL_UNAVAILABLE', '원격 에이전트가 요청을 처리하지 못했습니다.', 503);
      }
      try {
        const payload = await response.json();
        const answer = readA2AAnswer(payload);
        if (!answer) throw new AppError('MODEL_UNAVAILABLE', '원격 A2A 응답 형식이 올바르지 않습니다.', 503);
        return {
          answer,
          mode: input.mode,
          agent: agentName,
          sources: [],
          usage: null,
          requestId: payload.message?.messageId || input.requestId,
          confidence: null,
        };
      } catch (error) {
        if (error instanceof AppError) throw error;
        throw new AppError('MODEL_UNAVAILABLE', '원격 A2A 응답을 읽지 못했습니다.', 503);
      }
    },
  };
}

export async function discoverAgentCard({ cardUrl, timeoutMs = 5000, fetchImpl = fetch }) {
  let response;
  try {
    response = await fetchImpl(cardUrl, {
      method: 'GET',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw new AppError('MODEL_UNAVAILABLE', 'Agent Card에 연결할 수 없습니다.', 503);
  }
  if (!response.ok) {
    throw new AppError('MODEL_UNAVAILABLE', 'Agent Card를 가져오지 못했습니다.', 503);
  }
  let card;
  try {
    card = await response.json();
  } catch {
    throw new AppError('MODEL_UNAVAILABLE', 'Agent Card JSON을 읽지 못했습니다.', 503);
  }
  if (!card || typeof card.url !== 'string' || !card.url) {
    throw new AppError('MODEL_UNAVAILABLE', 'Agent Card에 유효한 url이 없습니다.', 503);
  }
  return card;
}

export function createDiscoveredHttpAgent({ agentName, cardUrl, headers = {}, timeoutMs = 5000, fetchImpl = fetch }) {
  let agentPromise;
  return {
    async ask(input) {
      agentPromise ??= discoverAgentCard({ cardUrl, timeoutMs, fetchImpl })
        .then((card) => {
          const standardInterface = card.supportedInterfaces?.find(
            (item) => item?.protocolBinding === 'HTTP+JSON' && typeof item.url === 'string',
          );
          return standardInterface
            ? createHttpJsonAgent({ agentName, endpoint: standardInterface.url, headers, timeoutMs, fetchImpl })
            : createHttpAgent({ agentName, endpoint: card.url, headers, timeoutMs, fetchImpl });
        });
      return (await agentPromise).ask(input);
    },
  };
}
