# 독자 세계관 데이터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CC0 자료를 참고 출처로 기록하면서, 독자 설정 세계관 3개를 `lore` Q&A에서 직접 조회할 수 있게 만든다.

**Architecture:** `data/knowledge.json`의 `lore` 항목에 독자 작성·참고 출처 메타데이터를 넣는다. `src/knowledge.js`는 기존 출처 URL에 더해 독자 세계관임을 알리는 `original:lore` 표식을 반환한다. 외부 게임의 인물, 지명, 줄거리는 데이터에 넣지 않는다.

**Tech Stack:** Node.js 20+, node:test, JSON 데이터 파일

## Global Constraints

- 외부 런타임 의존성을 추가하지 않는다.
- CC0 자료는 분위기·자산 분류 참고와 출처 기록에만 사용한다.
- 외부 게임 서사·인물·고유명사·대사를 복제하지 않는다.
- 모든 새 동작은 먼저 실패하는 테스트로 검증한다.
- 기존 `catalog`, `codex`, `lore` API 계약과 `npm test`를 유지한다.

## Execution Order

`glass-star-origin`은 Task 1의 테스트 대상이므로, 실행 시에는 **Task 2를 먼저 완료**해 세 세계관 데이터 시드를 추가한다. 그다음 Task 1을 실행해 `original:lore` 표식과 CC0 URL 반환을 검증한다. 마지막으로 전체 테스트를 실행한다.

---

### Task 1: 독자 세계관 출처 표식 반환

**Files:**
- Modify: `src/knowledge.js`
- Modify: `test/knowledge.test.js`

**Interfaces:**
- Consumes: `knowledge[mode]`의 항목 `originalContent?: boolean`, `sourceRef?: string`
- Produces: `lookupKnowledge(mode, question)`의 `{ answer: string, sources: string[] }`

- [ ] **Step 1: 독자 세계관 출처 테스트를 작성한다**

`test/knowledge.test.js`에 아래 테스트를 추가한다.

```js
test('독자 세계관 항목에는 original:lore 표식을 포함한다', () => {
  const result = lookupKnowledge('lore', '유리별은 어떻게 생겼나요?');
  assert.deepEqual(result.sources, [
    'lore:glass-star-origin',
    'original:lore',
    'https://opengameart.org/content/starfields',
  ]);
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `node --test test/knowledge.test.js`

Expected: `lore:glass-star-origin` 항목이 없어 테스트가 실패한다.

- [ ] **Step 3: 출처 표식 로직을 최소로 구현한다**

`src/knowledge.js`의 `sources` 생성 부분을 아래처럼 구성한다.

```js
const sources = [`${mode}:${item.id}`];
if (item.originalContent && mode === 'lore') sources.push('original:lore');
if (sourceUrl) sources.push(sourceUrl);
return { answer: item.answer, sources };
```

- [ ] **Step 4: 단위 테스트를 다시 실행한다**

Run: `node --test test/knowledge.test.js`

Expected: PASS

- [ ] **Step 5: 변경을 커밋한다**

```bash
git add src/knowledge.js test/knowledge.test.js
git commit -m "feat: mark original lore responses"
```

### Task 2: 독자 세계관 3개 시드 추가

**Files:**
- Modify: `data/knowledge.json`
- Modify: `test/knowledge.test.js`

**Interfaces:**
- Consumes: `sourceRef: "oga-starfields"` (이미 `data/sources.json`에 존재)
- Produces: `lore` 직접 조회 항목 `glass-star-origin`, `route-watch`, `faded-route-incident`

- [ ] **Step 1: 세력과 사건 조회 테스트를 작성한다**

`test/knowledge.test.js`에 아래 테스트를 추가한다.

```js
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `node --test test/knowledge.test.js`

Expected: 두 항목이 아직 없어 `null` 접근 오류 또는 assertion failure가 발생한다.

- [ ] **Step 3: `lore` 배열 앞에 독자 설정 항목을 추가한다**

`data/knowledge.json`의 `lore` 배열에 아래 형식의 항목을 추가한다.

```json
{
  "id": "glass-star-origin",
  "name": "유리별의 기원",
  "keywords": ["유리별", "유리별의 기원"],
  "answer": "유리별은 오래전 상층 대기가 굳어 만들어진 거대한 빛의 결정체라는 독자 설정입니다.",
  "sourceRef": "oga-starfields",
  "originalContent": true,
  "inspirationSources": ["oga-starfields"]
}
```

같은 구조로 `route-watch`와 `faded-route-incident`를 추가하고, 각각 `keywords`에 `항로 감시단`, `빛바랜 항로 사건`을 포함한다. 두 항목 모두 `sourceRef`, `originalContent`, `inspirationSources`에는 위와 같은 값을 넣는다.

- [ ] **Step 4: 전체 테스트를 실행한다**

Run: `npm test`

Expected: 모든 테스트가 PASS

- [ ] **Step 5: 변경을 커밋한다**

```bash
git add data/knowledge.json test/knowledge.test.js
git commit -m "feat: add original lore seed data"
```

## Self-Review

- 설계의 초기 3개 항목은 Task 2에서 모두 추가한다.
- `original:lore` 표식은 Task 1에서 구현하고 Task 2의 유리별 테스트로 검증한다.
- CC0 URL은 기존 `data/sources.json`의 `oga-starfields`를 재사용한다.
- 외부 의존성, 에셋 파일, 외부 게임 서사는 작업에 포함하지 않는다.
