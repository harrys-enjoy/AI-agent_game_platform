# 업무생산성 서비스 연동 계약

이 문서는 별도 업무생산성 서비스가 게임 Q&A API를 전문 A2A 에이전트로 호출하기 위한 최소 계약이다.

## 책임 경계

| 영역 | 담당 |
| --- | --- |
| 아침 업무 브리핑·업무 화면·중앙 오케스트레이션·MCP Host | 업무생산성 서비스 |
| 게임 기획·아트 가이드 및 카탈로그·도감·세계관 Q&A | 이 게임 Q&A API |
| 원격 전문 에이전트 선택 | 업무생산성 서비스의 오케스트레이터 |

이 저장소는 업무생산성 UI 또는 MCP Host를 구현하지 않는다.

## 연결 순서

1. `GET /.well-known/agent-card.json`으로 Agent Card를 조회한다.
2. `supportedInterfaces`에서 `protocolBinding: "HTTP+JSON"` 항목을 선택한다.
3. 해당 `url`의 `POST /message:send`로 질문을 보낸다.
4. 동기 `message` 또는 완료된 `task` 응답에서 텍스트를 표시한다.

Agent Card는 5분 동안 캐시할 수 있도록 `Cache-Control: public, max-age=300` 및 `ETag`를 제공한다.

## 인증과 브라우저 호출

`GAME_QNA_SERVICE_TOKEN`(구 이름 `API_KEY`도 계속 동작)이 설정된 환경에서는 `Authorization: Bearer <토큰>` 헤더가 필요하다. 키는 업무생산성 서비스의 서버 환경변수에만 보관하고 브라우저 코드, 프론트엔드 번들, 저장소에 넣지 않는다.

브라우저에서 직접 호출해야 한다면 이 API의 `CORS_ORIGIN`을 업무생산성 서비스의 정확한 Origin으로 설정한다. 사전 요청은 `authorization`과 `content-type` 헤더를 허용한다. 가능하면 키 노출을 막기 위해 업무생산성 서버를 경유한다.

## HTTP+JSON 요청 예시

```http
POST https://game-agent.example/message:send
Content-Type: application/a2a+json
Authorization: Bearer <GAME_QNA_SERVICE_TOKEN>

{
  "message": {
    "messageId": "briefing-20260728-001",
    "role": "ROLE_USER",
    "parts": [
      { "text": "오늘 검토할 전투 시스템 기획의 핵심 위험을 정리해줘." }
    ],
    "contextId": "project-demo"
  },
  "metadata": {
    "mode": "dev-guide",
    "context": {
      "projectId": "project-demo",
      "workContext": "morning-briefing"
    },
    "evidence": ["전투는 3인 협동 PvE를 목표로 한다."]
  }
}
```

`mode` 값은 `dev-guide`, `catalog`, `codex`, `lore` 중 하나다. `evidence`는 최대 5개, 각 1~2,000자, 전체 6,000자 이하다.

## 응답 처리

이 API는 현재 즉시 완료되는 텍스트 Q&A를 위해 아래 형식의 `message`를 반환한다.

```json
{
  "message": {
    "messageId": "briefing-20260728-001",
    "role": "ROLE_AGENT",
    "parts": [{ "text": "응답 내용" }]
  }
}
```

외부 A2A 에이전트 호출 시에는 완료된 `task.status.message.parts`의 텍스트도 지원한다. 스트리밍, 작업 조회·취소, 푸시 알림, 파일 파트는 현재 범위에 포함하지 않는다.

## 오류 처리

`/message:send`의 오류는 `application/a2a+json`으로 반환된다. `error.code`는 HTTP 상태 코드이고, `error.status`는 `INVALID_ARGUMENT`, `UNAUTHENTICATED`, `NOT_FOUND`, `UNAVAILABLE`, `INTERNAL` 중 하나다.

업무생산성 서비스는 `400`은 사용자 입력 수정 안내로, `401`은 서버 설정 오류로, `503`은 재시도 가능 안내로 처리한다. 질문·근거 전문이나 API 키는 로그에 남기지 않는다.

## 배포 전 확인 목록

- `AGENT_PUBLIC_URL`이 외부에서 접근 가능한 HTTPS 주소인지 확인한다.
- 업무생산성 서비스가 Agent Card를 읽고 `HTTP+JSON` 인터페이스를 선택하는지 확인한다.
- 서버 환경변수에만 `GAME_QNA_SERVICE_TOKEN`, 모델 API 키를 설정한다.
- `CORS_ORIGIN`이 필요한 경우 정확한 Origin 한 개로 설정한다.
- `npm test`가 통과한 상태에서 배포한다.
