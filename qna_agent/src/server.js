import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createHttpAgent } from './a2a.js';
import { toAgentRequest, toSendMessageResponse } from './a2a-http.js';
import { createAgentCard } from './agent-card.js';
import { createAgentRegistry } from './agents.js';
import { AppError } from './errors.js';
import { listSources, lookupKnowledge } from './knowledge.js';
import { createModelAdapterFromEnv } from './model-factory.js';
import { createOrchestrator } from './orchestrator.js';
import { createRequestId, parseJsonBody, validateAgentRequest, validateAskRequest } from './request.js';
import { loadEnvFile } from './config.js';

const MAX_BODY_BYTES = 1_048_576;

function writeJson(response, statusCode, body, headers = {}, contentType = 'application/json; charset=utf-8') {
  response.writeHead(statusCode, { 'content-type': contentType, ...headers });
  response.end(JSON.stringify(body));
}

function writeA2AError(response, error, headers) {
  const status = {
    400: 'INVALID_ARGUMENT',
    401: 'UNAUTHENTICATED',
    404: 'NOT_FOUND',
    503: 'UNAVAILABLE',
  }[error.statusCode] ?? 'INTERNAL';
  writeJson(response, error.statusCode, {
    error: {
      code: error.statusCode,
      status,
      message: error.message,
      details: [{
        '@type': 'type.googleapis.com/google.rpc.BadRequest',
        fieldViolations: [],
      }],
    },
  }, headers, 'application/a2a+json; charset=utf-8');
}

function corsHeaders(request, corsOrigin) {
  const origin = request.headers.origin;
  return corsOrigin && origin === corsOrigin
    ? {
      'access-control-allow-origin': corsOrigin,
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      'access-control-allow-headers': 'authorization, content-type',
      vary: 'Origin',
    }
    : {};
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new AppError('INVALID_REQUEST', '요청 본문은 1MB 이하이어야 합니다.'));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    request.on('error', reject);
  });
}

export function createDefaultOrchestrator({ modelAdapter = createModelAdapterFromEnv(), remoteAgents = {} } = {}) {
  const agents = createAgentRegistry({ modelAdapter });
  for (const [agentName, target] of Object.entries(remoteAgents)) {
    const agent = typeof target === 'string'
      ? createHttpAgent({ agentName, endpoint: target })
      : target;
    if (agent && typeof agent.ask === 'function') agents.set(agentName, agent);
  }
  return createOrchestrator({
    lookup: lookupKnowledge,
    agents,
  });
}

export function createServer({ orchestrator, modelAdapter, remoteAgents = {}, corsOrigin = process.env.CORS_ORIGIN || '', apiKey = process.env.GAME_QNA_SERVICE_TOKEN || process.env.API_KEY || '', publicUrl = process.env.AGENT_PUBLIC_URL || 'http://localhost:3000' } = {}) {
  orchestrator ??= createDefaultOrchestrator({ modelAdapter, remoteAgents });
  if (!orchestrator || typeof orchestrator.ask !== 'function') {
    throw new TypeError('orchestrator.ask가 필요합니다.');
  }

  return http.createServer(async (request, response) => {
    const requestId = createRequestId();
    const headers = corsHeaders(request, corsOrigin);
    try {
      if (request.method === 'OPTIONS' && ['/api/ask', '/a2a', '/message:send'].includes(request.url) && Object.keys(headers).length > 0) {
        response.writeHead(204, headers);
        response.end();
        return;
      }
      if (request.method === 'GET' && request.url === '/health') {
        writeJson(response, 200, { status: 'ok', service: 'game-qna-api' }, headers);
        return;
      }
      if (request.method === 'GET' && request.url === '/metrics') {
        writeJson(response, 200, orchestrator.getMetrics?.() ?? {
          cacheHits: 0,
          directKnowledgeResponses: 0,
          agentCalls: 0,
        }, headers);
        return;
      }
      if (request.method === 'GET' && request.url === '/sources') {
        writeJson(response, 200, { sources: listSources() }, headers);
        return;
      }
      if (request.method === 'GET' && request.url === '/.well-known/agent-card.json') {
        const card = createAgentCard({ publicUrl, requiresAuth: Boolean(apiKey) });
        const cardHeaders = {
          ...headers,
          'cache-control': 'public, max-age=300',
          etag: `"${card.name}-${card.version}"`,
        };
        if (request.headers['if-none-match'] === cardHeaders.etag) {
          response.writeHead(304, cardHeaders);
          response.end();
          return;
        }
        writeJson(response, 200, card, cardHeaders);
        return;
      }
      if (apiKey && ['/api/ask', '/a2a', '/message:send'].includes(request.url) && request.headers.authorization !== `Bearer ${apiKey}`) {
        throw new AppError('UNAUTHORIZED', '유효한 Bearer 인증이 필요합니다.', 401);
      }
      const isAskRequest = request.method === 'POST' && request.url === '/api/ask';
      const isA2ARequest = request.method === 'POST' && request.url === '/a2a';
      const isA2AHttpRequest = request.method === 'POST' && request.url === '/message:send';
      if (!isAskRequest && !isA2ARequest && !isA2AHttpRequest) {
        throw new AppError('INTERNAL_ERROR', '요청 경로를 찾을 수 없습니다.', 404);
      }
      const parsed = parseJsonBody(await readBody(request));
      const body = isA2AHttpRequest
        ? toAgentRequest(parsed)
        : isA2ARequest ? validateAgentRequest(parsed) : validateAskRequest(parsed);
      const result = await orchestrator.ask({ ...body, requestId: isAskRequest ? requestId : body.requestId });
      const responseBody = isA2AHttpRequest
        ? toSendMessageResponse(result)
        : isA2ARequest ? { ...result, confidence: null } : result;
      writeJson(response, 200, responseBody, headers, isA2AHttpRequest ? 'application/a2a+json; charset=utf-8' : undefined);
    } catch (error) {
      const appError = error instanceof AppError
        ? error
        : new AppError('INTERNAL_ERROR', '서버에서 요청을 처리하지 못했습니다.', 500);
      if (request.method === 'POST' && request.url === '/message:send') {
        writeA2AError(response, appError, headers);
        return;
      }
      writeJson(response, appError.statusCode, {
        error: { code: appError.code, message: appError.message, requestId },
      }, headers);
    }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  loadEnvFile();
  const port = Number(process.env.PORT || 3000);
  createServer().listen(port, () => {
    console.log(`game-qna-api listening on ${port}`);
  });
}
