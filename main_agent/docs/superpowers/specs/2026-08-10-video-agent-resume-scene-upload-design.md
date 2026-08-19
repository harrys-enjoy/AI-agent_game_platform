# Video-agent 씬 재개 업로드 설계

## 목표

video-agent가 일부 장면을 수동 수정 대상으로 반환할 때 MAIN이 `taskId`와 `unresolvedScenes`를 프론트엔드에 전달하고, 사용자가 수정 이미지를 업로드해 해당 장면의 재개 endpoint를 호출할 수 있도록 한다.

## 범위

- `chat_reply()` 응답에 `taskId`와 `unresolvedScenes`를 조건부로 포함한다.
- MAIN에 `POST /api/video-agent/tasks/{task_id}/scenes/{scene_id}/resume` 프록시를 추가한다.
- multipart 업로드 의존성을 추가하고 video-agent의 성공·A2A 오류·연결 오류를 기존 API 오류 형식으로 매핑한다.
- 프론트엔드 채팅에 미해결 씬 카드, 썸네일, 이슈, 이미지 업로드 입력을 추가한다.
- 업로드 결과의 `remaining_unresolved`를 카드 상태에 반영하고, 최종 영상 URL이 반환되면 메시지로 표시한다.

## 비범위

- 기존 스토리 검토/승인 기능, Workmate 연동, PreviewPanel 동작 변경
- video-agent 저장소 자체의 변경
- 업로드 후 자동 polling

## 설계

백엔드는 기존 `AgentRegistry`의 video-agent base URL과 인증 헤더를 재사용한다. 업로드 파일은 `httpx.AsyncClient(timeout=300.0)`로 video-agent의 동일한 resume 경로에 multipart로 전달한다. 오류 응답은 `A2AError.from_payload()`로 변환하고, 연결·비구조화 오류는 502로 반환한다.

프론트엔드는 `resume-utils.ts`에 씬 상태와 FormData 생성 로직을 둔다. 채팅 응답에 미해결 씬이 있으면 `unresolved-scenes` 메시지를 만들고, 사용자가 파일을 선택하면 해당 씬만 uploading 상태로 바꾼다. 성공 시 서버가 반환한 남은 씬 목록으로 카드를 갱신하며, 모든 씬이 해결되고 `output_video_url`이 있으면 완료 메시지를 추가한다.

## 검증

- 기존 백엔드 전체 pytest 통과
- 새 프록시 route의 성공, video-agent 오류 매핑, 연결 실패 502 테스트 통과
- 기존 프론트엔드 테스트와 resume 유틸 테스트 통과
- 프론트엔드 TypeScript/Vite build 통과
