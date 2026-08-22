# 내부 Agent Chat 상호 라우팅 설계

## 목표

Workmate AI, Video Generation, Development Assistant, Game Q&A의 어느 내부 Chat에서 입력하더라도, 요청 의도에 맞는 전문 Agent가 처리하게 한다. 사용자는 대화 중 탭을 직접 바꾸지 않아도 되며, 기존 전문 Agent의 실행·저장·확인 절차는 유지한다.

## 범위와 비범위

이 변경은 `main_agent`의 프론트엔드와 오케스트레이터 백엔드만 수정한다.

- Workmate Agent의 일정, 회의, Task 원장, 승인 API 및 데이터베이스는 수정하지 않는다.
- Video, Development, Game Q&A Agent의 요청 계약과 도메인 로직은 수정하지 않는다.
- Main Agent는 일정·회의·Task를 직접 생성하지 않는다. 선택된 Agent에 자연어 요청과 기존 확인 정보를 전달할 뿐이다.
- Game Q&A의 명령어(`/planning`, `/art`, `/lore`, `/catalog`, `/codexbook`, `/story-review`)는 명시적 선택으로 간주해 기존 동작을 유지한다.

## 라우팅 계약

### 입력

`POST /api/chats/{agent_name}/reply`는 기존처럼 원래 Chat 이름과 메시지를 받는다. `agent_name`은 사용자가 입력한 화면의 출처이며, 전문 Agent를 고정하는 값이 아니다.

### 결정

백엔드는 모든 내부 Chat의 일반 자연어 입력에 대해 공통 라우터를 호출한다.

1. 라우터가 신뢰도 기준을 통과한 하나의 Agent를 선택하면 해당 Agent에 전달한다.
2. 라우터가 선택하지 못하거나 복수 후보를 반환하면 실행하지 않는다.
3. 이 경우 응답은 `status: "needs_agent_selection"` 및 선택 가능한 Agent 목록을 반환한다.
4. 프론트엔드는 선택 카드를 표시한다. 사용자가 하나를 선택하면 같은 원문에 선택 Agent를 명시해 재전송한다.
5. 명시적 Game Q&A 명령어는 라우터보다 우선한다.

### 응답

일반 성공 응답에는 기존 `answer`, `agent`, `status`, `pending_action` 필드를 유지한다. 프론트엔드는 `agent`가 입력 Chat과 다를 경우 실제 담당 Agent의 내부 Chat으로 자동 전환하고, `Game Q&A에서 전달됨`처럼 전달 출처를 표시한다. 원래 요청과 응답은 대상 Agent의 대화 기록으로 함께 저장해, 전환 후에도 대화 맥락이 이어진다.

## Task 및 Workmate 보호 경계

프론트엔드의 공통 Project Task 제안은 자연어의 `일정`, `회의`, `추가`, `등록` 조합만으로 실행하면 안 된다. 자동 제안은 사용자가 `Task`, `작업`, `할 일`을 명시한 경우에만 가능하다.

따라서 `회의 일정 추가해줘`는 Workmate로 라우팅되어 정보 확인 또는 Workmate의 기존 승인 흐름을 따른다. `이 내용을 Task로 추가해줘`만 Project Task 제안 흐름을 유지한다.

Workmate가 `pending_action`을 반환하면 현재의 확인 카드 및 재전송 계약을 그대로 사용한다. Main Agent는 그 확인을 Workmate Agent의 기존 동작에만 전달하며, Workmate 데이터 저장소를 직접 호출하지 않는다.

## 모호성 규칙

라우터가 사용할 수 없거나 신뢰도 미달인 경우에는 화면 출처를 폴백으로 사용하지 않는다. 사용자에게 아래 네 Agent를 선택하게 한다.

- Workmate AI
- Video Generation
- Development Assistant
- Game Q&A

선택 전에는 외부 Agent 호출, Project Task 생성, Workmate 실행 확인이 발생하지 않는다.

## 오류 처리

- 라우터 응답이 형식에 맞지 않거나 시간 초과되면 모호성 응답으로 처리한다.
- 사용자가 허용되지 않은 Agent를 선택하면 422를 반환한다.
- 전문 Agent 호출 실패는 현재처럼 오류 응답으로 표시하고, 원래 Chat 기록에 남긴다.

## 검증 기준

1. Game Q&A에서 일정·회의 요청 시 Workmate Agent로 전달된다.
2. Workmate에서 게임 세계관 요청 시 Game Q&A Agent로 전달된다.
3. `회의 일정 추가해줘`는 Project Task 제안을 표시하지 않는다.
4. `Task로 추가해줘`는 기존 Project Task 확인 흐름을 유지한다.
5. 모호한 요청은 Agent 선택 카드만 표시하며 전문 Agent를 호출하지 않는다.
6. 자동 전달된 성공 응답은 실제 담당 Agent의 Chat으로 화면이 전환되고, 전달 출처와 함께 표시된다.
7. Workmate Agent의 소스·API·DB 마이그레이션 파일은 변경하지 않는다.
