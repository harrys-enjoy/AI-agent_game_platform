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
