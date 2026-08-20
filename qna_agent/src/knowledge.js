import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { normalizeLocale } from './locales.js';

const dataPath = fileURLToPath(new URL('../data/knowledge.json', import.meta.url));
const knowledge = JSON.parse(readFileSync(dataPath, 'utf8'));
const sourcesPath = fileURLToPath(new URL('../data/sources.json', import.meta.url));
const sourceData = JSON.parse(readFileSync(sourcesPath, 'utf8'));
const loreLocalesPath = fileURLToPath(new URL('../data/lore-locales.json', import.meta.url));
const loreLocales = JSON.parse(readFileSync(loreLocalesPath, 'utf8'));
const storyPath = fileURLToPath(new URL('../data/stories/side-story-ashes-ledger.json', import.meta.url));
const storyEntries = JSON.parse(readFileSync(storyPath, 'utf8'));
const storyLocalesPath = fileURLToPath(new URL('../data/story-locales.json', import.meta.url));
const storyLocales = JSON.parse(readFileSync(storyLocalesPath, 'utf8'));
const reviewedStoriesPath = fileURLToPath(new URL('../data/stories/reviewed-stories.json', import.meta.url));
let reviewedStoryEntries = [];
try {
  const parsedReviewedStories = JSON.parse(readFileSync(reviewedStoriesPath, 'utf8'));
  reviewedStoryEntries = Array.isArray(parsedReviewedStories) ? parsedReviewedStories : [];
} catch {
  reviewedStoryEntries = [];
}
const mergedKnowledge = {
  ...knowledge,
  lore: [...(knowledge.lore ?? []), ...storyEntries, ...reviewedStoryEntries],
};

function localizedEntry(entry, locale = 'ko') {
  const selectedLocale = normalizeLocale(locale) || 'ko';
  const translation = selectedLocale === 'ko'
    ? null
    : storyLocales[entry.id]?.[selectedLocale] ?? loreLocales[entry.id]?.[selectedLocale];
  return {
    ...entry,
    name: translation?.name ?? entry.name,
    keywords: translation?.keywords ?? entry.keywords,
    answer: translation?.answer ?? entry.answer,
  };
}

export function validateKnowledgeSources(data, sources) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  for (const entries of Object.values(data)) {
    for (const entry of entries) {
      if (!entry.sourceRef) continue;
      const source = sourceById.get(entry.sourceRef);
      if (!source) throw new Error(`출처 ID를 찾을 수 없습니다: ${entry.sourceRef}`);
      if (source.license !== 'CC0') throw new Error(`출처는 CC0 라이선스여야 합니다: ${entry.sourceRef}`);
    }
  }
}

validateKnowledgeSources(mergedKnowledge, sourceData);
const sourceById = new Map(sourceData.map((source) => [source.id, source]));
const loreOverviewTerms = ['\uC138\uACC4\uAD00', '\uC124\uC815', '\uC2A4\uD1A0\uB9AC', '\uAC8C\uC784 \uC138\uACC4'].map(normalizeSearchText);
const loreOverview = {
  answer: '\uC774 \uAC8C\uC784\uC758 \uC138\uACC4\uAD00\uC740 \uC720\uB9AC\uBCC4\uC758 \uBE5B\uACFC \uAE30\uC5B5\uC744 \uB458\uB7EC\uC2FC \uD56D\uB85C \uC0AC\uD68C\uC758 \uC774\uC57C\uAE30\uC785\uB2C8\uB2E4. \uC720\uB9AC\uBCC4\uC758 \uC2EC\uC7A5\uC5D0\uB294 \uC0AC\uB78C\uB4E4\uC758 \uAE30\uC5B5\uACFC \uC2E0\uBD84 \uAE30\uB85D\uC774 \uC800\uC7A5\uB418\uC5B4 \uC788\uACE0, \uD56D\uB85C\uC640 \uAC70\uC810\uC744 \uC9C0\uBC30\uD558\uB824\uB294 \uC9C8\uC11C\uC758 \uC138\uB825\uACFC \uC790\uC720\uC640 \uACF5\uB3D9\uCCB4\uB97C \uC120\uD0DD\uD558\uB824\uB294 \uC804\uC6B0\uCE58\uC758 \uBC14\uB78C\uC758 \uB3C4\uC801\uB2E8\uC774 \uCDA9\uB3CC\uD569\uB2C8\uB2E4. \uD64D\uAE38\uB3D9\uC740 \uD3C9\uB4F1\uD55C \uACF5\uB3D9\uCCB4\uC640 \uADDC\uCE59\uC744 \uC138\uC6B0\uB824 \uD558\uBA70, \uC5F0\uD654\uB294 \uC774\uB4E4\uC758 \uAE30\uB85D\uACFC \uC9C4\uC2E4\uC744 \uC5F0\uACB0\uD558\uB294 \uC911\uB9BD\uC790\uC785\uB2C8\uB2E4.\n\n\uD575\uC2EC \uAC08\uB4F1\uC740 \uC790\uC720\uC640 \uC9C8\uC11C, \uAC1C\uC778\uC758 \uD798\uACFC \uACF5\uB3D9\uCCB4\uC758 \uC548\uC804, \uAE30\uB85D\uC744 \uBCF4\uC874\uD558\uB294 \uAC83\uACFC \uC0C8\uB85C \uC6B0\uB9AC\uB97C \uB9CC\uB4DC\uB294 \uAC83 \uC0AC\uC774\uC758 \uC120\uD0DD\uC785\uB2C8\uB2E4.',
  sources: ['lore:overview', 'original:lore'],
  mode: 'lore',
};

export function listSources() {
  return sourceData.map(({ id, title, sourceUrl, license, licenseUrl, usage }) => ({
    id,
    title,
    sourceUrl,
    license,
    licenseUrl,
    usage,
  }));
}

export function normalizeSearchText(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .toLocaleLowerCase('ko-KR')
    .replace(/\s+/g, '')
    .replace(/[^\p{L}\p{N}]/gu, '');
}

export function listKnowledge(mode, { full = false, locale = 'ko' } = {}) {
  return (mergedKnowledge[mode] ?? []).map((entry) => {
    const localized = localizedEntry(entry, locale);
    const summary = { id: entry.id, name: localized.name, keywords: [...localized.keywords] };
    if (!full) return summary;
    return {
      ...summary,
      answer: localized.answer,
      sourceRef: entry.sourceRef ?? null,
      originalContent: entry.originalContent ?? false,
      inspirationSources: entry.inspirationSources ?? [],
      relatedLoreIds: entry.relatedLoreIds ?? [],
      relatedCodexIds: entry.relatedCodexIds ?? [],
    };
  });
}

export function lookupKnowledge(mode, question, locale = 'ko') {
  const normalizedQuestion = normalizeSearchText(question);
  const entries = mergedKnowledge[mode] ?? [];
  let item = null;
  let bestMatchLength = 0;
  for (const entry of entries) {
    const localized = localizedEntry(entry, locale);
    const matchedLength = Math.max(...[localized.name, ...localized.keywords, entry.name, ...entry.keywords]
      .map((term) => normalizeSearchText(term))
      .filter((term) => term && normalizedQuestion.includes(term))
      .map((term) => term.length), 0);
    if (matchedLength > bestMatchLength) {
      item = entry;
      bestMatchLength = matchedLength;
    }
  }
  if (!item) {
    if (mode === 'lore' && loreOverviewTerms.some((term) => normalizedQuestion === term || normalizedQuestion.includes(term))) return loreOverview;
    return null;
  }
  const localized = localizedEntry(item, locale);
  const sourceUrl = sourceById.get(item.sourceRef)?.sourceUrl;
  const sources = [`${mode}:${item.id}`];
  if (item.originalContent && mode === 'lore') sources.push('original:lore');
  if (sourceUrl) sources.push(sourceUrl);
  return { answer: localized.answer, sources };
}

export function appendReviewedStory(entry) {
  reviewedStoryEntries.push(entry);
  mergedKnowledge.lore.push(entry);
}

export function lookupKnowledgeBest(question, locale = 'ko') {
  const normalizedQuestion = normalizeSearchText(question);
  const modes = ['lore', 'catalog', 'codex'];
  let best = null;

  for (const mode of modes) {
    for (const entry of mergedKnowledge[mode] ?? []) {
      const localized = localizedEntry(entry, locale);
      const terms = [localized.name, ...localized.keywords, entry.name, ...entry.keywords]
        .map(normalizeSearchText)
        .filter(Boolean);
      const matchedLength = Math.max(...terms.filter((term) => normalizedQuestion.includes(term)).map((term) => term.length), 0);
      if (matchedLength === 0) continue;
      const exact = terms.some((term) => term === normalizedQuestion);
      const score = (exact ? 100_000 : 0) + matchedLength;
      if (!best || score > best.score) best = { mode, name: localized.name, score };
    }
  }

  if (best) return { ...lookupKnowledge(best.mode, best.name, locale), mode: best.mode };
  const overview = lookupKnowledge('lore', question, locale);
  return overview?.sources?.[0] === 'lore:overview' ? overview : null;
}
