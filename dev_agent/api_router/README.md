# api_router

모델 서버 관련 잡동사니.

- `main.py` — Elice mlapi.run 엔드포인트가 응답하는지 확인하는 스모크 스크립트
  (`ELICE_API_KEY` 필요). 실제 클라이언트 로직은 `graph/llm_client.py`에 있다 —
  여기 있는 건 수동 확인용 사본일 뿐, 로직을 바꿀 땐 그쪽을 고칠 것.

컨테이너 진입점이 아니라 `.dockerignore` 화이트리스트에서 빠져 있다(이미지에 안 들어감).
