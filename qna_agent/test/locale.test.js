import test from 'node:test';
import assert from 'node:assert/strict';
import { lookupKnowledge, listKnowledge } from '../src/knowledge.js';
import { validateAskRequest } from '../src/request.js';

test('lore는 영어 locale로 전우치 콘텐츠를 반환한다', () => {
  const result = lookupKnowledge('lore', 'Jeon Woo-chi', 'en');
  assert.equal(result.sources[0], 'lore:jeonuchi-freedom');
  assert.match(result.answer, /freedom|records/i);
});

test('lore 전체 콘텐츠는 일본어와 중국어 번역을 반환한다', () => {
  const japanese = listKnowledge('lore', { full: true, locale: 'ja' })
    .find((entry) => entry.id === 'honggildong-order');
  const chinese = listKnowledge('lore', { full: true, locale: 'zh-CN' })
    .find((entry) => entry.id === 'honggildong-order');
  assert.match(japanese.name, /ホン|チョン/);
  assert.match(chinese.name, /洪/);
  assert.notEqual(japanese.answer, chinese.answer);
});

test('지원하지 않는 locale은 요청 오류로 거부한다', () => {
  assert.throws(
    () => validateAskRequest({ mode: 'lore', locale: 'fr', question: 'test' }),
    (error) => error.code === 'INVALID_REQUEST',
  );
});

test('locale이 없으면 한국어를 기본값으로 사용한다', () => {
  assert.equal(validateAskRequest({ mode: 'lore', question: '전우치' }).locale, 'ko');
});
