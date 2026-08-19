# kosa 멀티에이전트 시스템 — 모델 카드

마지막 갱신: 2026-08-03

## 개요

`kosa`는 GitHub PR/레포에 대한 자연어 요청("이 PR 리뷰해줘", "브랜치 현황 정리해줘", "테스트 돌려줘", "배포해줘")을 받아 필요한 작업만 골라 실행하는 LangGraph 기반 멀티에이전트다. 진입점은 두 곳:

- [app.py](../app.py) — Streamlit 인터랙티브 UI
- [a2a_server.py](../a2a_server.py) — 팀 A2A 규약(`POST /a2a/v1/message:send`)을 받는 동기 HTTP 엔드포인트

둘 다 [graph/build.py](../graph/build.py)의 동일한 `build_graph()` 그래프를 그대로 실행한다.

## 아키텍처

```
supervisor (LLM, 1회 upfront 계획)
   │
   ├─ fetch          (결정론적)
   ├─ review_agent    (LLM)
   ├─ endpoint_agent  (LLM)
   ├─ branch_agent    (LLM)
   ├─ ci_agent        (LLM, 조건부)
   ├─ ci_trigger      (결정론적, 쓰기)
   └─ deploy_trigger  (결정론적, 쓰기)
          │
          └─ compose_final_response (결정론적 조합)
```

`supervisor_node`가 요청을 딱 한 번 읽고 실행할 노드 리스트를 통째로 계획한 뒤([graph/supervisor.py:98](../graph/supervisor.py:98)), 그 이후로는 LangGraph가 리스트를 순서대로 소비한다 — 중간 결과를 보고 계획을 다시 세우는 ReAct형 적응 루프가 아니다. 이 트레이드오프(예측 가능성/비용 vs 적응력)는 "알려진 한계" 절 참고.

## 사용 모델

라우팅 계획과 워커 4종 모두 Elice `mlapi.run` 호스팅 엔드포인트 하나를 공유한다
([graph/llm_client.py](../graph/llm_client.py)) — 자체 학습/파인튜닝 없음. 예전에는 라우팅(로컬 vllm/qwen4b)과
워커(NVIDIA NIM)가 서로 다른 두 엔드포인트를 썼으나, 하나로 통합했다.

| 용도 | 위치 | timeout | max_tokens |
|---|---|---|---|
| 라우팅 계획 (프롬프트로 JSON 요청) | [graph/supervisor.py](../graph/supervisor.py) | 45s | 4096 |
| 워커 4종 (review/endpoint/branch/ci) | [graph/workers.py](../graph/workers.py) | 30s | 16000 |

라우팅은 이전에는 vLLM의 guided decoding(구조화 출력)으로 JSON을 강제했지만, 지금은 프롬프트로
JSON만 답하도록 요청하고 응답에서 JSON 블록을 정규식으로 추출해 파싱한다
([graph/supervisor.py](../graph/supervisor.py)의 `_parse_routing_plan`). 파싱 실패 시 재시도 없이 즉시 예외를 던진다 —
구조화 출력 대비 신뢰도가 떨어질 수 있는 지점이라, 실패가 반복되면 개선이 필요하다.

## 노드별 상세

| 노드 | 결정론? | 하는 일 |
|---|---|---|
| `fetch` | ✅ | GitHub API로 diff/브랜치/PR/CI 체크 결과 조회. LLM 없음 |
| `review_agent` | ❌ (LLM) | PR diff를 파일:라인 단위로 리뷰. diff 없으면 LLM 호출 안 함 |
| `endpoint_agent` | ❌ (LLM) | PR diff 안에서 라우트/엔드포인트 **변경**만 감지, 문서 갱신 제안. 레포의 현재 엔드포인트 전체 목록 조회는 지원 안 함 |
| `branch_agent` | ❌ (LLM) | 브랜치/PR 목록으로 진행 현황 요약 |
| `ci_agent` | 조건부 | 실패한 CI 로그가 있을 때만 LLM 호출, 없으면 결정론적 메시지 |
| `ci_trigger` | ✅ | GitHub Actions 워크플로를 실제로 실행·대기. 쓰기 동작 |
| `deploy_trigger` | ✅ | 로컬 Docker Desktop에 실제 배포 (Dockerfile 또는 docker-compose). 쓰기 동작 |
| `compose_final_response` | ✅ | 워커 결과를 마크다운으로 조립. LLM 없음 |

## 알려진 한계 (이번 세션에서 실측)

1. **라우팅 과다 포함** — nemotron 라우터가 좁은 요청("브랜치 현황 정리해줘")에도 `review_agent`/`ci_trigger`/`deploy_trigger`까지 계획에 넣는 것을 실측. 특히 `ci_trigger`/`deploy_trigger`는 실제 쓰기 동작이라 위험 → `_gate_explicit_actions()`로 코드 레벨 게이트 적용([graph/supervisor.py:74](../graph/supervisor.py:74)).
2. **빈 diff 할루시네이션** — diff가 비었는데도 `review_agent`/`endpoint_agent`가 존재하지 않는 pandas/Java 코드를 지어내 리뷰한 것을 실측 → 빈 diff 가드로 LLM 호출 자체를 막음([graph/workers.py:8](../graph/workers.py:8), [:22](../graph/workers.py:22)).
3. **외부 LLM API 불안정성** — 같은 호출이 성공/401/타임아웃을 반복하는 것을 여러 번 관찰 → 타임아웃/연결오류/429/5xx만 backoff 재시도(최대 3회)하고 401/404 같은 확정적 오류는 즉시 포기하도록 `graph/llm_client.py`의 `chat_completion()`에 재시도 로직을 적용(supervisor/workers 공용). 폴백 모델은 여전히 없음.
4. **단일 upfront 계획** — fetch 결과를 보고 LLM이 재계획하지는 않는다. 대신 코드로 보정한다: diff가 비면 diff 의존 워커를 빼고(`_drop_diff_workers_when_diff_missing`), 레포 자체가 없으면 즉시 종료(`_end_early_on_fatal_fetch_error`).
5. **compose 헬스체크 한계** — `dockersamples/todo-list-app`으로 실제 배포해서 확인: `docker compose ps`가 "running"을 보고해도 앱이 `yarn install` 중이라 실제 HTTP 응답까진 30초 이상 더 걸림. "배포 완료" 응답이 "요청 받을 준비 완료"를 보장하지 않음.
6. **history_context는 Streamlit UI 전용** — `supervisor.py`가 `state["history_context"]`를 읽어 플래너 프롬프트에 최근 대화를 얹는다([app.py](../app.py) 경로). A2A 경로([a2a_server.py](../a2a_server.py))는 항상 빈 값을 넘긴다 — 프로세스 전역 이력을 쓰면 서로 다른 `user_id`/`workspace_id`의 요청이 한 프롬프트에 섞이기 때문. A2A에서 이력이 필요하면 `workspace_id`/`contextId` 단위로 분리해 보관해야 한다.
7. **endpoint_agent는 목록 조회 불가** — diff 안의 변경 감지만 하고, 레포의 현재 엔드포인트 전체 목록은 못 뽑음(구조 변경 필요, 미착수).

## 적용된 안전장치

- `_gate_explicit_actions()` — `ci_trigger`/`deploy_trigger`는 요청 문구에 실제 키워드가 있을 때만 실행되도록 코드로 강제(모델 프롬프트 준수에만 의존하지 않음)
- `_order_ci_before_summary()` — `ci_trigger`가 `ci_agent`보다 항상 먼저 실행되도록 순서 보장
- `_slot_name()` — 컨테이너/이미지 이름을 레포별로 분리, 동시 배포는 파일 락으로 차단
- A2A 서버 인증은 fail-closed — `A2A_SERVICE_TOKEN` 미설정 시 503으로 거부(무인증 통과 없음)

## 테스트/평가

- 단위 테스트 145개 (`pytest tests/`), 대부분 결정론적 노드는 fake run/fake LLM으로 오프라인 검증. CI로 자동 실행되진 않고(`.github/workflows` 없음) 코드 변경 때마다 로컬에서 수동으로 돌림
- `deploy_trigger` compose 지원은 실제 Docker Desktop + 실제 공개 레포(`dockersamples/todo-list-app`)로 라이브 검증 완료 (컨테이너 기동 → HTTP 200 확인 → 정리)
- A2A 엔드포인트는 실제 uvicorn 서버 + curl로 팀 규약 포맷 그대로 라이브 검증 완료, main_agent(오케스트레이터)와도 실제 docker compose로 붙여 종단 검증 완료
- `test_a2a_server.py`가 `dotenv.load_dotenv()`를 임포트 시점에 실행해, `pytest tests/`를 통째로 돌리면 원래 오프라인 스킵이던 `test_routing.py`의 `requires_elice_api` 테스트가 실제 Elice API 호출을 타는 부작용이 있음(미해결, 사용자 확인 대기 중)

## 범위 밖 (Out of scope)

- A2A 경로의 대화 이력 (workspace 단위 분리 저장 미구현 — Streamlit UI에서만 동작)
- 레포 전체 엔드포인트 목록 조회
- docker-compose 배포의 접속 URL 자동 파싱 (YAML 파서 미사용, 사용자가 `docker compose ps`로 직접 확인해야 함)
- 단일 컨테이너 배포 헬스체크의 "HTTP GET `/`" 가정 (compose 외 정적 로직 미변경)

## 의도된 사용

내부 팀이 GitHub PR 관련 반복 작업(리뷰 초안, 현황 요약, CI 재실행, 로컬 배포)을 자연어로 위임하는 보조 도구. **LLM 산출물(리뷰/문서 갱신 제안)은 초안으로만 취급해야 하며, 실제 머지/배포 승인의 유일한 근거로 쓰면 안 된다** — 위 한계 2번(할루시네이션)과 3번(API 불안정성)이 실측된 상태.
