# Workmate Agent 메인 UI 연결 설계

## 목표

기존 `mock-agents`의 Workmate 서비스를 `workmate-agent-main` 프로젝트로 교체하고, 메인 UI의 `Workmate AI` 채팅이 실제 Workmate A2A 에이전트와 통신하도록 연결한다.

## 현재 구조

- 메인 API는 `AgentRegistry`로 에이전트 카드를 조회하고, `A2AClient`로 메시지를 전송한다.
- Docker Compose의 `workmate-agent` 서비스는 현재 `./mock-agents`를 빌드한다.
- 새 Workmate 에이전트는 `GET /.well-known/agent-card.json`, `POST /a2a/message:send`, `GET /a2a/tasks/{task_id}`를 제공한다.
- 새 에이전트는 `Authorization: Bearer ...`와 `A2A-Version: 1.0`을 요구하고, 첫 메시지 파트의 JSON 데이터에 `skill_id`를 요구한다.

## 설계

1. Compose의 `workmate-agent` 빌드 컨텍스트를 `../workmate-agent-main`으로 변경한다. 서비스명과 내부 포트는 기존과 같은 `workmate-agent:8001`을 유지한다.
2. `WORKMATE_SERVICE_TOKEN`을 메인 API와 Workmate 컨테이너에 동일하게 주입한다. 기본값은 빈 문자열이 아니라 명시적인 환경 변수로 두어 인증 누락을 조기에 드러낸다.
3. `A2AClient`가 HTTP+JSON 요청을 만들 때 `A2A-Version: 1.0`을 추가하고, Workmate 호환성을 위해 첫 파트에 `skill_id`와 원문 메시지를 JSON 데이터로 넣는다. 기존 범용 에이전트 호출은 유지한다.
4. Workmate용 요청 생성은 `build_agent_request`에서 `daily_briefing`을 기본 skill로 사용한다. 이후 skill 라우팅 확장은 별도 범위로 둔다.
5. Compose healthcheck와 `depends_on.condition: service_healthy`로 메인 API가 준비된 Workmate에 연결되도록 한다.

## 실패 처리

- 인증 누락/오류는 기존 A2A 오류 매핑을 유지한다.
- Workmate 카드 조회 실패는 해당 에이전트를 unavailable로 표시하며 메인 API 자체는 기동한다.
- Workmate 요청의 지원하지 않는 skill은 400 오류로 전달되어 UI에 사용자 친화적인 메인 API 오류로 표시된다.

## 검증 기준

- 메인 테스트에서 HTTP+JSON 요청에 `A2A-Version`과 `skill_id`가 포함되는지 확인한다.
- Compose 설정이 새 폴더를 빌드하고 동일 토큰을 전달하는지 정적 검증한다.
- Workmate smoke test와 메인 백엔드 전체 테스트를 실행한다.
- Docker Compose 기동 후 `/health`, `/api/agents`, Workmate readiness 및 실제 채팅 요청을 확인한다.
