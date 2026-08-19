import { once } from 'node:events';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/server.js';

test('GET /sources는 CC0 출처 목록을 반환한다', async () => {
  const server = createServer({ orchestrator: { ask: async () => ({}) } }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/sources`);
  const body = await response.json();
  server.close();

  assert.equal(response.status, 200);
  assert.equal(body.sources[0].license, 'CC0');
  assert.equal(body.sources[0].sourceUrl, 'https://opengameart.org/content/rpg-tileset');
});
