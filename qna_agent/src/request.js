import { AppError } from './errors.js';
import { normalizeLocale } from './locales.js';

export const ALLOWED_MODES = new Set(['dev-guide', 'catalog', 'codex', 'lore']);
const MAX_EVIDENCE_ITEMS = 5;
const MAX_EVIDENCE_ITEM_CHARS = 2000;
const MAX_EVIDENCE_TOTAL_CHARS = 6000;

export function parseJsonBody(rawBody) {
  try {
    return JSON.parse(rawBody);
  } catch {
    throw new AppError('INVALID_REQUEST', '요청 본문은 유효한 JSON이어야 합니다.');
  }
}

export function validateAskRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new AppError('INVALID_REQUEST', '요청 본문은 JSON 객체여야 합니다.');
  }
  if (!ALLOWED_MODES.has(body.mode)) {
    throw new AppError('INVALID_REQUEST', 'mode는 지원되는 값이어야 합니다.');
  }
  if (typeof body.question !== 'string') {
    throw new AppError('INVALID_REQUEST', 'question은 문자열이어야 합니다.');
  }
  const question = body.question.trim();
  if (question.length < 1 || question.length > 2000) {
    throw new AppError('INVALID_REQUEST', 'question은 1~2,000자여야 합니다.');
  }
  const locale = normalizeLocale(body.locale);
  if (!locale) {
    throw new AppError('INVALID_REQUEST', 'locale??ko, en, ja, zh-CN 以묒뿉???섏뼱???⑸땲??');
  }
  const context = body.context ?? {};
  if (!context || typeof context !== 'object' || Array.isArray(context)) {
    throw new AppError('INVALID_REQUEST', 'context는 JSON 객체여야 합니다.');
  }
  return { mode: body.mode, locale, question, context };
}

export function createRequestId() {
  return `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function validateAgentRequest(body) {
  const request = validateAskRequest(body);
  const requestId = typeof body.requestId === 'string' && body.requestId.trim()
    ? body.requestId.trim()
    : createRequestId();
  const evidence = body.evidence ?? [];
  if (!Array.isArray(evidence) || evidence.some((item) => typeof item !== 'string')) {
    throw new AppError('INVALID_REQUEST', 'evidence는 문자열 배열이어야 합니다.');
  }
  if (evidence.length > MAX_EVIDENCE_ITEMS) {
    throw new AppError('INVALID_REQUEST', `evidence는 최대 ${MAX_EVIDENCE_ITEMS}개까지 허용됩니다.`);
  }
  const normalizedEvidence = evidence.map((item) => item.trim());
  if (normalizedEvidence.some((item) => item.length < 1 || item.length > MAX_EVIDENCE_ITEM_CHARS)) {
    throw new AppError('INVALID_REQUEST', `각 evidence는 1~${MAX_EVIDENCE_ITEM_CHARS}자여야 합니다.`);
  }
  if (normalizedEvidence.join('').length > MAX_EVIDENCE_TOTAL_CHARS) {
    throw new AppError('INVALID_REQUEST', `evidence 전체 길이는 ${MAX_EVIDENCE_TOTAL_CHARS}자 이하여야 합니다.`);
  }
  return { ...request, requestId, evidence: normalizedEvidence };
}
