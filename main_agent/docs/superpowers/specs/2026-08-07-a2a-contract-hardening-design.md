# A2A 계약 표준화 및 CAT 연동 강화 설계

## 목표

MAIN 저장소의 기존 A2A 초기 구현을 팀 공통 합의안에 맞게 정리한다. 전문 Agent의 내부 구현은 바꾸지 않고, MAIN의 A2A 경계에서 Agent Card discovery, HTTP+JSON A2A 1.0, 환경변수 registry, Service Token, Task/Polling, CAT 오류 처리를 일관되게 제공한다.

## 범위

1. Agent Card의 `supportedInterfaces`에서 HTTP+JSON 1.0 endpoint를 선택한다.
2. Agent 목록과 endpoint/token 설정을 환경변수에서 읽는다.
3. A2A 호출 시 선택적으로 `Authorization: Bearer <token>`을 전송한다.
4. 동기 `message`와 완료 Task 응답을 해석하고, 비동기 Task 상태를 polling한다.
5. CAT의 `/message:send` 오류를 공통 오류 모델로 변환해 API 응답과 Task 결과에 보존한다.

## 설계

### A2A 계약 계층

`AgentCard`는 표준 메타데이터를 보존한다. Registry는 base URL에서 Agent Card를 발견하고, Client는 Card의 HTTP+JSON 1.0 interface를 선택한다. 표준 interface가 없으면 기존 JSON-RPC endpoint를 호환 경로로 사용한다.

요청은 `application/a2a+json`을 사용하며 `messageId`, `ROLE_USER`, 텍스트 parts, `metadata.mode`, `metadata.locale`, `metadata.context`, `metadata.evidence`를 포함한다. 응답은 `message.parts`, `task.status.message.parts`, `task.artifacts` 순서로 텍스트를 찾는다.

### 환경변수 registry와 인증

`AGENT_REGISTRY`가 쉼표로 구분한 Agent 이름을 결정한다. 각 Agent는 `<NAME>_AGENT_URL` 및 선택적 `<NAME>_AGENT_TOKEN`으로 설정한다. 기존 `GAME_QNA_AGENT_URL`과 `GAME_QA_AGENT_URL`은 호환성을 위해 fallback으로 유지한다.

토큰은 서버 환경변수에서만 읽고 HTTP 요청 헤더에만 사용한다. 토큰이 없는 Agent에는 Authorization 헤더를 보내지 않는다.

### Task/Polling

MAIN API는 즉시 자체 Task ID를 반환하고 백그라운드에서 Agent를 실행한다. Agent가 Task ID를 반환하면 Client가 설정된 간격으로 상태를 조회한다. 완료 결과는 기존 `TaskRecord.result`에 저장하고, 실패·부분 성공은 `error`와 Agent별 event에 보존한다. 프론트엔드는 terminal status까지 MAIN Task를 polling한다.

### CAT 오류

CAT `/message:send`의 A2A 오류 payload에서 `error.code`, `error.status`, `error.message`, `requestId`를 읽어 `A2AError`로 표준화한다. 인증, 입력, 미발견, 일시적 장애, 내부 오류를 각각 HTTP 상태에 매핑한다. `/api/stories`는 Catalog 지식 API의 도메인 endpoint로 유지하고 A2A 오류 처리와 분리한다.

## 테스트 전략

- Agent Card interface 선택 및 필드 보존
- HTTP+JSON content type, metadata, token header
- 동기 message, 완료 Task, polling timeout
- CAT 오류 payload 변환 및 상태 매핑
- 환경변수 registry 구성
- MAIN Task API와 frontend polling 계약
- Docker Compose 설정 검증

## 성공 기준

- 기존 테스트를 유지하면서 새 계약 테스트가 통과한다.
- `python -m pytest -q`가 통과한다.
- `npm run build`와 기존 frontend 테스트가 통과한다.
- `docker compose config`가 성공한다.
- 실제 Catalog의 Agent Card와 `/message:send` 연동 테스트가 통과하거나, Docker 미실행 환경에서는 명확한 환경 제약으로 보고된다.
