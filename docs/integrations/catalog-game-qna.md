# Catalog & Manual Game Q&A 연결

## 연결 대상

- 프로젝트: `../Catalog & Manual(Game project)`
- 서비스명: `game-qa-agent`
- 컨테이너 포트: `3000`
- Agent Card: `http://game-qa-agent:3000/.well-known/agent-card.json`
- A2A HTTP+JSON: `http://game-qa-agent:3000/message:send`

## Main Agent 연결 방식

Main Agent는 Agent Card를 조회한 뒤 `supportedInterfaces`의 HTTP+JSON 엔드포인트를 사용합니다. 요청은 Catalog 프로젝트가 요구하는 형식으로 변환됩니다.

```json
{
  "message": {
    "messageId": "main-agent",
    "role": "ROLE_USER",
    "parts": [{"text": "게임 세계관을 설명해줘"}]
  },
  "metadata": {
    "mode": "game_qa",
    "locale": "ko"
  }
}
```

MAIN은 Card의 `supportedInterfaces`에서 `protocolBinding: "HTTP+JSON"`, `protocolVersion: "1.0"` 항목을 선택합니다. `GAME_QNA_AGENT_TOKEN`이 설정된 경우 호출에 `Authorization: Bearer <token>`을 추가하며 token은 서버 환경변수에만 둡니다.

Catalog가 완료 Task를 반환하는 경우 MAIN은 Task URL을 polling하고 `message.parts`, `task.status.message.parts`, `task.artifacts` 순서로 답변 텍스트를 읽습니다. 오류는 Catalog의 `application/a2a+json` 오류 계약을 유지한 채 Main API 상태 코드로 매핑합니다.

## 실행

Main Agent 폴더에서 다음 명령을 실행합니다.

```bash
docker compose up --build
```

현재 실행 환경에는 Docker CLI가 없어 실제 컨테이너 간 통신은 아직 검증하지 못했습니다. Catalog 프로젝트 자체의 Node 테스트 77개와 Main Agent의 Python 테스트 10개는 통과했습니다.

## 나머지 Agent 추적 대상

- 업무지원 Agent
- 영상 생성 Agent
- 개발 보조 Agent

각 프로젝트가 준비되면 Agent Card URL, A2A 엔드포인트, 컨테이너 포트만 추가하면 됩니다.
