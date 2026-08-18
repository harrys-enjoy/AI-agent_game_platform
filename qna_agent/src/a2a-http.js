import { AppError } from './errors.js';
import { createRequestId, validateAgentRequest } from './request.js';

function invalid(message) {
  throw new AppError('INVALID_REQUEST', message);
}

export function toAgentRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    invalid('A2A 요청 본문은 JSON 객체여야 합니다.');
  }
  const { message } = body;
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    invalid('message 객체가 필요합니다.');
  }
  if (message.role !== 'ROLE_USER') {
    invalid('message.role은 ROLE_USER여야 합니다.');
  }
  if (!Array.isArray(message.parts) || message.parts.length === 0) {
    invalid('message.parts는 하나 이상의 텍스트 파트를 포함해야 합니다.');
  }
  if (message.parts.some((part) => !part || typeof part.text !== 'string')) {
    invalid('현재는 텍스트 A2A 파트만 지원합니다.');
  }

  const metadata = body.metadata ?? {};
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    invalid('metadata는 JSON 객체여야 합니다.');
  }
  const metadataContext = metadata.context ?? {};
  if (!metadataContext || typeof metadataContext !== 'object' || Array.isArray(metadataContext)) {
    invalid('metadata.context는 JSON 객체여야 합니다.');
  }
  const context = { ...metadataContext };
  if (typeof message.contextId === 'string' && message.contextId.trim()) {
    context.contextId = message.contextId.trim();
  }

  return validateAgentRequest({
    requestId: typeof message.messageId === 'string' && message.messageId.trim()
      ? message.messageId.trim()
      : createRequestId(),
    mode: metadata.mode ?? 'dev-guide',
    question: message.parts.map((part) => part.text).join('\n'),
    context,
    evidence: metadata.evidence ?? [],
  });
}

export function toSendMessageResponse(result) {
  return {
    message: {
      messageId: result.requestId,
      role: 'ROLE_AGENT',
      parts: [{ text: result.answer }],
    },
  };
}
