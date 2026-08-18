# 게임 개발 Q&A API 설계

## 1. 목표

외부 업무생산성 서비스가 업무 중 필요한 게임 제작 정보를 요청할 수 있는 독립형 Q&A API를 만든다. 메인 기능은 게임 기획·아트 가이드 Q&A이며, 게임 카탈로그·도감·세계관 Q&A를 확장 기능으로 제공한다.

업무생산성 메인페이지, 아침 업무 브리핑 화면, 외부 인증·데이터베이스는 이 프로젝트의 범위에 포함하지 않는다.

## 2. 사용 흐름

```text
외부 업무생산성 서비스
  -> POST /api/ask
  -> 입력 검증
  -> mode 기반 최소 라우팅
  -> 직접 데이터 조회 또는 필요한 단일 에이전트 호출
  -> 표준 응답 반환
```

외부 서비스는 아침 업무 브리핑 또는 업무 중 화면에서 이 API를 호출한다. UI는 API 소비자가 선택할 수 있도록 독립형으로 유지하며, 별도 임베드 UI는 API MVP 이후에 추가한다.

## 3. 핵심 기능

### 3.1 개발 가이드 Q&A

`dev-guide` 모드가 기획, 캐릭터, 시스템, 레벨, 아트 스타일, UI/UX 관련 질문을 처리한다. 질문에 맞는 가이드 자료만 컨텍스트로 넣고, 자료가 없으면 추측하지 않고 필요한 자료를 요청한다.

### 3.2 카탈로그·도감·세계관 Q&A

다음 모드는 확장 기능으로 동일한 API 계약을 사용한다.

| mode | 용도 | 기본 처리 |
| --- | --- | --- |
| `catalog` | 게임 콘텐츠 목록·분류 | 데이터 직접 조회 우선 |
| `codex` | 캐릭터·몬스터·아이템 도감 | 데이터 직접 조회 우선 |
| `lore` | 세계관·세력·관계·사건 | 관련 자료 검색 후 응답 |

정확한 구조화 데이터로 답할 수 있는 질문은 모델을 호출하지 않는다.

## 4. API 계약

### 요청

```http
POST /api/ask
Content-Type: application/json
```

```json
{
  "mode": "dev-guide",
  "question": "중세 판타지 마을의 색상 팔레트를 추천해줘",
  "context": {
    "projectId": "demo-game",
    "userId": "user-123",
    "workContext": "morning-briefing"
  }
}
```

필수 필드:

- `mode`: `dev-guide`, `catalog`, `codex`, `lore` 중 하나
- `question`: 공백을 제거한 뒤 1~2,000자

선택 필드:

- `context.projectId`: 외부 프로젝트 식별자
- `context.userId`: 외부 사용자 식별자
- `context.workContext`: `morning-briefing`, `in-progress` 등 호출 맥락

### 응답

```json
{
  "answer": "저채도 갈색을 기반으로 ...",
  "mode": "dev-guide",
  "agent": "art-guide",
  "sources": [],
  "usage": {
    "inputTokens": 0,
    "outputTokens": 0
  },
  "requestId": "req_01H..."
}
```

`usage` 값은 모델 제공자가 반환하지 않으면 `null`로 둔다. 토큰 수를 임의로 계산해 정확한 값처럼 표시하지 않는다.

### 오류

오류도 JSON으로 반환한다.

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "mode는 지원되는 값이어야 합니다.",
    "requestId": "req_01H..."
  }
}
```

최소 오류 코드:

- `INVALID_REQUEST`: 요청 형식 또는 길이 오류
- `UNSUPPORTED_MODE`: 지원하지 않는 mode
- `KNOWLEDGE_NOT_FOUND`: 신뢰할 수 있는 자료 없음
- `MODEL_UNAVAILABLE`: 모델 제공자 호출 실패
- `INTERNAL_ERROR`: 예상하지 못한 서버 오류

## 5. 오케스트레이션

초기 오케스트레이터는 하나의 짧은 라우터로 유지한다.

```text
ask(request)
  1. mode와 question 검증
  2. catalog/codex는 구조화 데이터 조회
  3. 직접 조회 불가 시 mode별 agent 선택
  4. 필요한 자료만 검색
  5. 모델 어댑터에 짧은 프롬프트와 제한된 컨텍스트 전달
  6. 표준 응답으로 정규화
```

초기에는 질문 하나에 여러 에이전트를 병렬 호출하지 않는다. 여러 전문 에이전트의 합성이 실제 요구사항으로 확인될 때만 추가한다.

내부 에이전트 이름은 다음처럼 고정한다.

- `planning-guide`
- `art-guide`
- `catalog`
- `codex`
- `lore`

## 6. A2A 확장 경계

A2A를 나중에 연결할 수 있도록 오케스트레이터와 에이전트 사이에 다음 논리적 계약을 둔다.

```text
AgentRequest {
  requestId: string
  mode: string
  question: string
  context: object
  evidence: array
}

AgentResponse {
  answer: string
  agent: string
  sources: array
  usage: object | null
  confidence: number | null
}
```

현재 에이전트는 로컬 함수 또는 Mock 구현으로 동작한다. 향후 외부 A2A 에이전트가 연결되더라도 `/api/ask`의 외부 계약은 유지하고, 오케스트레이터 내부의 에이전트 호출부만 교체한다.

별도 A2A 네트워크, 에이전트 레지스트리, 재시도 큐, 워크플로 엔진은 초기 MVP에서 만들지 않는다.

## 7. Elice ML API 연결 전략

Elice ML API의 실제 엔드포인트·인증·요청 형식은 기술 문서가 확보된 후 연결한다. 현재는 제공자별 코드를 API 라우트에 직접 넣지 않고 다음 단일 경계만 둔다.

```text
ModelAdapter.generate(prompt, options) -> ModelResult
```

MVP에서는 `MockModelAdapter`를 사용해 API 동작과 토큰 절감 흐름을 검증한다. Elice 명세가 확보되면 `EliceModelAdapter`를 추가하고 환경변수로 선택한다. API 키는 소스 코드나 클라이언트에 노출하지 않는다.

## 8. 토큰 절감 원칙

- 구조화 데이터로 답할 수 있으면 모델을 호출하지 않는다.
- 전체 문서 대신 검색된 관련 조각만 전달한다.
- 전체 대화 이력 대신 최근 질문과 짧은 요약만 사용한다.
- mode별 짧은 시스템 지침을 사용한다.
- 기본 출력 길이를 제한한다.
- 실패 시 여러 모델을 연쇄 호출하지 않는다.
- 동일한 프로젝트·mode·질문·자료 버전 조합은 캐시할 수 있게 키를 정한다.
- `usage`를 기록하되 토큰 절감을 위해 상세 로그에 원문 프롬프트를 저장하지 않는다.

## 9. 보안·신뢰성

- 요청 본문 크기와 질문 길이를 제한한다.
- 외부 입력은 모델 지침보다 높은 권한을 갖지 않는다.
- 모델이 근거 없는 설정을 만들지 않도록 자료가 없을 때 명시적으로 응답한다.
- API 키와 사용자 식별자를 로그에 그대로 남기지 않는다.
- 모든 요청에 `requestId`를 부여해 오류 추적이 가능하게 한다.
- 모델 제공자 오류는 표준 `MODEL_UNAVAILABLE`로 변환한다.

## 10. MVP 성공 기준

1. 외부 클라이언트가 `POST /api/ask` 하나로 질문할 수 있다.
2. `dev-guide` 질문이 Mock 에이전트를 통해 응답된다.
3. `catalog`, `codex`, `lore` 모드가 같은 계약으로 동작한다.
4. 구조화 데이터 질문은 모델 호출 없이 응답된다.
5. 잘못된 요청과 모델 오류가 표준 오류 JSON으로 반환된다.
6. Elice ML API를 나중에 연결할 위치와 입력·출력 경계가 문서화되어 있다.
7. 토큰 사용량을 확인할 수 있으나 제공자가 측정하지 않은 값은 조작하지 않는다.

## 11. 범위 밖 항목

- 업무생산성 서비스의 메인페이지와 아침 업무 브리핑 UI
- 외부 서비스의 로그인·권한·사용자 DB
- 실제 Elice ML API 연동
- 실제 외부 A2A 에이전트 연동
- 실시간 스트리밍 응답
- 복수 에이전트 합성 워크플로
- 관리자용 지식 편집 화면
