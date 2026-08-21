# Main Agent Handoff Routing Design

## Goal

Main Chat은 사용자의 원문을 바꾸지 않고 담당 Agent를 선택한 뒤 해당 Agent Chat으로 전환·자동 전달한다. 실제 답변과 작업 실행은 선택된 Agent만 수행한다.

## Scope

이 설계의 변경 범위는 `main_agent/backend`와 `main_agent/frontend`다. Workmate AI, Video Generation, Development Assistant, Game Q&A의 업무 스키마·실행 API·승인 규칙은 변경하지 않는다.

## Ownership Boundary

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Main Chat / Main backend router | 담당 Agent 선택, 화면 대상 반환, 원문 전달 | 답변 생성, 업무 실행, 세부 작업 스키마 판별 |
| Selected Agent Chat | 원문 수신, 해당 Agent의 스키마 판별, 실행, 답변 표시 | 다른 Agent로 재라우팅 |

## Routing Contract

Main 전용 라우팅 요청은 사용자 원문을 받는다. 성공 응답은 아래 계약을 사용한다.

```json
{
  "targetAgent": "workmate-agent",
  "targetChat": "Workmate AI",
  "originalRequest": "오늘 브리핑 해줘",
  "handoff": "automatic"
}
```

- `targetAgent`는 `workmate-agent`, `video-agent`, `dev-agent`, `game-qna-agent` 중 하나다.
- `targetChat`은 해당 Agent의 UI 채팅 이름이다.
- `originalRequest`는 trim 처리 외에 수정·요약·명령 변환을 하지 않은 사용자 원문이다.
- `handoff`는 `automatic` 또는 `confirmation_required`다. Video Generation은 생성 비용·실행 확인이 필요하므로 항상 `confirmation_required`다.
- 라우터가 신뢰 가능한 Agent를 선택하지 못하면 API는 성공 응답을 만들지 않고, Main UI는 답변 폴백 대신 담당 Agent를 판단하지 못했다는 상태만 표시한다.

## Data Flow

```text
Main Chat 입력
  -> Main routing API
  -> { targetAgent, targetChat, originalRequest, handoff }
  -> targetChat 화면 전환
  -> automatic: targetChat의 기존 reply API에 originalRequest 자동 전송
  -> confirmation_required: targetChat 입력에 originalRequest를 채움
  -> 선택된 Agent가 응답 또는 실행 상태를 targetChat에 표시
```

Main Chat에는 연결 상태 메시지만 남긴다. Agent의 응답 본문은 Main Chat에 복사하거나 저장하지 않는다.

## Backend Rules

1. Main 전용 라우팅 endpoint는 `RouterLLM.select()` 결과 또는 기존 deterministic fallback으로 Agent를 하나 선택한다.
2. `/api/chats/Main Chatbot/reply`는 실제 Agent를 호출하지 않는다. 호환성 유지가 필요하면 routing endpoint로 동일한 handoff 결과만 반환한다.
3. `/api/chats/{agent_name}/reply`에서 `agent_name`이 실제 Agent Chat 이름이면 그 Agent의 고정 card를 사용한다. 입력 내용으로 다른 Agent를 선택하지 않는다.
4. Main 이외의 호출이 명시적 라우팅 entry point일 때만 routing helper를 사용한다.

## Frontend Rules

1. `submitMainChat()`은 Main routing API만 호출한다. 기존 Main 답변 API 호출과 `createChatReply()` 폴백을 제거한다.
2. routing 응답을 받으면 `targetChat`을 활성화하고, `originalRequest`를 기존 Agent Chat reply 흐름에 자동 전송한다.
3. 자동 전달 중에는 target Agent Chat의 작업 상태를 `working`으로 보이고, 성공·실패 상태는 기존 Agent Chat 흐름과 동일하게 처리한다.
4. Video Generation은 `confirmation_required`로 전환하고 원문만 영상 브리프 입력에 채운다. Main Chat은 영상 초안이나 영상 작업을 생성하지 않는다.

## Error Handling

- Main routing API 실패: Main Chat에 라우팅 실패 상태만 표시하고 원문을 실행하지 않는다.
- Agent Chat 전송 실패: 선택된 Agent Chat에 해당 오류만 표시한다. Main Chat은 연결 상태를 유지한다.
- Agent 응답 실패: 기존 Agent별 오류 표현을 유지한다.

## Verification

- Backend: Main routing response의 계약, Main reply가 Agent를 호출하지 않는지, 고정 Agent Chat이 재라우팅되지 않는지 테스트한다.
- Frontend: Main 입력이 routing API를 호출하는지, 선택된 화면으로 전환되는지, 원문이 한 번만 Agent reply API로 자동 전송되는지 테스트한다.
- Regression: Game Q&A 명령과 Story Review Workspace, Video Generation 화면 전환을 유지한다.
