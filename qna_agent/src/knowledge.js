import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dataPath = fileURLToPath(new URL('../data/knowledge.json', import.meta.url));
const knowledge = JSON.parse(readFileSync(dataPath, 'utf8'));
const sourcesPath = fileURLToPath(new URL('../data/sources.json', import.meta.url));
const sourceData = JSON.parse(readFileSync(sourcesPath, 'utf8'));

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

validateKnowledgeSources(knowledge, sourceData);
const sourceById = new Map(sourceData.map((source) => [source.id, source]));

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

export function lookupKnowledge(mode, question) {
  const entries = knowledge[mode] ?? [];
  const item = entries.find((entry) => entry.keywords.some((keyword) => question.includes(keyword)));
  if (!item) return null;
  const sourceUrl = sourceById.get(item.sourceRef)?.sourceUrl;
  const sources = [`${mode}:${item.id}`];
  if (item.originalContent && mode === 'lore') sources.push('original:lore');
  if (sourceUrl) sources.push(sourceUrl);
  return { answer: item.answer, sources };
}
