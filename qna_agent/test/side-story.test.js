import { once } from 'node:events';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';
import { lookupKnowledge } from '../src/knowledge.js';

test('재의 장부 번외편은 영어·일본어·중국어로 조회된다', () => {
  const questions = { en: 'Ashes Ledger', ja: '灰の帳簿', 'zh-CN': '灰烬账簿' };
  for (const locale of Object.keys(questions)) {
    const result = lookupKnowledge('lore', questions[locale], locale);
    assert.equal(result.sources[0], 'lore:side-ashes-ledger');
    assert.ok(result.answer.length > 20);
  }
});

test('lore 전체 콘텐츠 응답에 재의 장부 번외편이 포함된다', async () => {
  const server = createServer().listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/knowledge?mode=lore&full=true`);
  const body = await response.json();
  server.close();
  assert.equal(response.status, 200);
  assert.ok(body.entries.some((entry) => entry.id === 'side-third-banner'));
});
