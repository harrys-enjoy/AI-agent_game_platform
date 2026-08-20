import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { AppError } from './errors.js';
import { MockModelAdapter } from './model.js';

const defaultStoryPath = fileURLToPath(new URL('../data/stories/reviewed-stories.json', import.meta.url));
const REVIEW_TTL_MS = 30 * 60 * 1000;

function validateDraft(draft) {
  if (!draft || typeof draft !== 'object' || Array.isArray(draft)) throw new AppError('INVALID_REQUEST', '스토리 초안은 JSON 객체여야 합니다.', 400);
  for (const field of ['name', 'answer']) {
    if (typeof draft[field] !== 'string' || !draft[field].trim()) throw new AppError('INVALID_REQUEST', `${field}는 필수 문자열입니다.`, 400);
  }
  if (!Array.isArray(draft.keywords) || draft.keywords.length < 1 || draft.keywords.some((item) => typeof item !== 'string' || !item.trim())) {
    throw new AppError('INVALID_REQUEST', 'keywords는 비어 있지 않은 문자열 배열이어야 합니다.', 400);
  }
  for (const field of ['relatedLoreIds', 'relatedCodexIds']) {
    if (draft[field] !== undefined && (!Array.isArray(draft[field]) || draft[field].some((item) => typeof item !== 'string'))) {
      throw new AppError('INVALID_REQUEST', `${field}는 문자열 배열이어야 합니다.`, 400);
    }
  }
  return {
    name: draft.name.trim(),
    keywords: draft.keywords.map((item) => item.trim()),
    answer: draft.answer.trim(),
    relatedLoreIds: draft.relatedLoreIds ?? [],
    relatedCodexIds: draft.relatedCodexIds ?? [],
  };
}

function readStore(storyPath) {
  try {
    const value = JSON.parse(readFileSync(storyPath, 'utf8'));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeStore(storyPath, entries) {
  mkdirSync(dirname(storyPath), { recursive: true });
  writeFileSync(storyPath, `${JSON.stringify(entries, null, 2)}\n`, 'utf8');
}

function buildEvidence(draft, listKnowledge) {
  const evidence = [];
  for (const [mode, ids] of [['lore', draft.relatedLoreIds], ['codex', draft.relatedCodexIds]]) {
    const entries = listKnowledge(mode, { full: true }) ?? [];
    for (const id of ids) {
      const entry = entries.find((item) => item.id === id);
      if (entry) evidence.push(`${mode}:${entry.id}\n${entry.name}\n${entry.answer}`);
    }
  }
  if (evidence.length === 0) {
    const query = `${draft.name} ${draft.keywords.join(' ')} ${draft.answer}`;
    for (const mode of ['lore', 'codex']) {
      const entries = listKnowledge(mode, { full: true }) ?? [];
      for (const entry of entries) {
        if ([entry.name, ...(entry.keywords ?? [])].some((term) => query.includes(term))) {
          evidence.push(`${mode}:${entry.id}\n${entry.name}\n${entry.answer}`);
        }
      }
    }
  }
  return evidence.slice(0, 5);
}

function normalizeReview(raw, evidence, usage, reviewId) {
  let parsed;
  const rawText = String(raw ?? '').trim();
  const fencedText = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  const objectStart = fencedText.indexOf('{');
  const objectEnd = fencedText.lastIndexOf('}');
  const candidates = [
    fencedText,
    objectStart >= 0 && objectEnd > objectStart ? fencedText.slice(objectStart, objectEnd + 1) : '',
  ].filter(Boolean);
  try {
    for (const candidate of candidates) {
      try {
        parsed = JSON.parse(candidate);
        break;
      } catch {
        // Try the next JSON candidate when the model added prose around the object.
      }
    }
    if (!parsed) throw new Error('Structured review JSON was not found.');
  } catch {
    parsed = {
      verdict: 'review_required',
      suggestions: [rawText || '스토리 본문, 사건 인과관계, 캐릭터 목표와 행동을 더 구체적으로 입력해 주세요.'],
    };
  }
  const arrays = ['continuityConflicts', 'timelineIssues', 'characterConsistency', 'factionConsistency', 'missingRelationships', 'suggestions'];
  const formatFinding = (item) => {
    if (typeof item === 'string') return item;
    if (item && typeof item === 'object') {
      const content = typeof item.content === 'string' ? item.content.trim() : '';
      const reason = typeof item.reason === 'string' ? item.reason.trim() : '';
      if (content && reason) return `${content} — ${reason}`;
      if (content || reason) return content || reason;
    }
    return String(item ?? '').trim();
  };
  const result = Object.fromEntries(arrays.map((key) => [key, Array.isArray(parsed[key]) ? parsed[key].map(formatFinding).filter(Boolean) : []]));
  const verdict = ['pass', 'review_required', 'reject'].includes(parsed.verdict) ? parsed.verdict : 'review_required';
  if (verdict === 'review_required' && arrays.every((key) => result[key].length === 0)) {
    result.suggestions = ['스토리 본문, 사건 인과관계, 캐릭터 목표와 행동을 더 구체적으로 입력해 주세요.'];
  }
  return { reviewId, verdict, ...result, evidence: evidence.map((item) => item.split('\n', 1)[0]), usage: usage ?? null, approvalRequired: verdict !== 'pass' };
}

export function createStoryReviewService({ modelAdapter, listKnowledge, storyPath = defaultStoryPath, onApproved }) {
  if (!modelAdapter || typeof modelAdapter.generate !== 'function') throw new TypeError('modelAdapter.generate가 필요합니다.');
  if (typeof listKnowledge !== 'function') throw new TypeError('listKnowledge가 필요합니다.');
  const reviews = new Map();
  const rpgReviewSystem = 'RPG 스토리 검토 전문가다. 제공된 근거만 사실로 사용하고 근거 밖의 설정은 추측하지 않는다. 세계관 요약으로 끝내지 말고 사건 인과관계, 타임라인, 캐릭터 목표와 행동 일관성, 세력의 이해관계와 관계 변화, 기존 Lore/Codex와의 설정 충돌, 플레이어가 경험할 갈등과 개선 방향을 검토한다. 반드시 verdict와 continuityConflicts, timelineIssues, characterConsistency, factionConsistency, missingRelationships, suggestions 배열을 가진 JSON만 반환한다.';
  const rpgReviewQuestion = (draft) => `다음 RPG 스토리 초안을 서사적으로 검토해줘. 각 문제는 초안의 구체적인 내용과 제공된 근거를 연결해 설명하고, 문제가 없으면 빈 배열을 반환해. 검토 대상: 사건 인과관계, 타임라인, 캐릭터 동기와 일관성, 세력 관계, Lore/Codex 설정 충돌, 누락된 관계, 게임 플레이로 발전시킬 수 있는 개선안. 초안:\n${JSON.stringify(draft)}`;

  return {
    async review(input) {
      const draft = validateDraft(input);
      const reviewId = `review-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      const evidence = buildEvidence(draft, listKnowledge);
      if (modelAdapter instanceof MockModelAdapter) {
        const result = normalizeReview('', evidence, null, reviewId);
        reviews.set(reviewId, { draft, result, expiresAt: Date.now() + REVIEW_TTL_MS });
        return result;
      }
      const result = await modelAdapter.generate({
        system: '스토리 검토자다. 제공된 근거만 사실로 사용한다. 근거 밖의 설정은 추측하지 않는다. 반드시 verdict와 배열 필드를 가진 JSON만 반환한다.',
        question: `다음 스토리 초안의 기존 설정 충돌, 전후관계, 인물·세력 일관성, 누락된 관계를 검토해줘. 초안:\n${JSON.stringify(draft)}`,
        evidence,
        maxOutputChars: 6000,
        system: rpgReviewSystem,
        question: rpgReviewQuestion(draft),
      });
      const normalized = normalizeReview(result.answer, evidence, result.usage, reviewId);
      reviews.set(reviewId, { draft, result: normalized, expiresAt: Date.now() + REVIEW_TTL_MS });
      return normalized;
    },
    approve(reviewId, input) {
      const stored = reviews.get(reviewId);
      if (!stored || stored.expiresAt <= Date.now()) throw new AppError('STORY_REVIEW_EXPIRED', '승인 가능한 검토 결과가 없습니다.', 409);
      const draft = validateDraft(input);
      if (JSON.stringify(draft) !== JSON.stringify(stored.draft) || stored.result.verdict !== 'pass') throw new AppError('STORY_REVIEW_REQUIRED', '승인 가능한 검토 결과가 없습니다.', 409);
      const entries = readStore(storyPath);
      const id = draft.id ?? `${draft.name.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '')}-${Date.now().toString(36)}`;
      if (entries.some((entry) => entry.id === id)) throw new AppError('STORY_DUPLICATE', '같은 스토리 ID가 이미 존재합니다.', 409);
      const entry = { id, ...draft, originalContent: true, sourceRef: null, inspirationSources: [], storyArc: 'reviewed' };
      writeStore(storyPath, [...entries, entry]);
      onApproved?.(entry);
      reviews.delete(reviewId);
      return { status: 'saved', entry };
    },
  };
}
