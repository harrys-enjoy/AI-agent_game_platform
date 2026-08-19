import test from 'node:test';
import assert from 'node:assert/strict';
import { lookupKnowledge, validateKnowledgeSources } from '../src/knowledge.js';

test('출처가 있는 지식 항목은 CC0 출처를 참조해야 한다', () => {
  assert.throws(
    () => validateKnowledgeSources(
      { lore: [{ id: 'lore-1', sourceRef: 'non-cc0' }] },
      [{ id: 'non-cc0', license: 'CC-BY-4.0' }],
    ),
    /CC0/,
  );
});

test('존재하지 않는 출처 ID는 거부한다', () => {
  assert.throws(
    () => validateKnowledgeSources(
      { codex: [{ id: 'codex-1', sourceRef: 'missing-source' }] },
      [],
    ),
    /missing-source/,
  );
});

test('카탈로그의 키워드 하나만 포함해도 항목을 찾는다', () => {
  const result = lookupKnowledge('catalog', '마을 정보를 보여줘');
  assert.deepEqual(result.sources, ['catalog:ember-village']);
});

test('CC0 오픈 게임 소스 기반 도감 항목을 조회한다', () => {
  const result = lookupKnowledge('codex', '무료 게임 오브젝트에 어떤 것이 있나요?');
  assert.deepEqual(result.sources, [
    'codex:oga-free-game-objects',
    'https://opengameart.org/content/free-game-objects',
  ]);
});

test('독자 세계관의 세력과 사건을 직접 조회한다', () => {
  assert.equal(
    lookupKnowledge('lore', '항로 감시단은 어떤 세력인가요?').sources[0],
    'lore:route-watch',
  );
  assert.equal(
    lookupKnowledge('lore', '빛바랜 항로 사건을 알려줘').sources[0],
    'lore:faded-route-incident',
  );
});

test('독자 세계관 항목에는 original:lore 표식을 포함한다', () => {
  const result = lookupKnowledge('lore', '유리별은 어떻게 생겼나요?');
  assert.deepEqual(result.sources, [
    'lore:glass-star-origin',
    'original:lore',
    'https://opengameart.org/content/starfields',
  ]);
});

test('codex 질문은 모델 없이 도감 데이터를 반환한다', () => {
  const result = lookupKnowledge('codex', '루멘의 약점은 무엇인가?');
  assert.equal(result.answer, '루멘의 약점은 냉기 속성입니다.');
  assert.deepEqual(result.sources, ['codex:lumens']);
});

test('자료가 없는 질문은 null을 반환한다', () => {
  assert.equal(lookupKnowledge('catalog', '없는 아이템을 보여줘'), null);
});
