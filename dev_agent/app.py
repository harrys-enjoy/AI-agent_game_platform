import os

import streamlit as st
from dotenv import load_dotenv

from graph.build import build_graph
from graph.history import format_recent, new_history, record_turn

load_dotenv()

st.set_page_config(page_title="개발 보조 에이전트", layout="wide")
st.title("개발 보조 멀티에이전트")

if not os.getenv("ELICE_API_KEY"):
    st.error("ELICE_API_KEY가 설정되지 않았습니다. 환경변수 파일에 키를 넣어주세요.")
    st.stop()

if "graph" not in st.session_state:
    st.session_state.graph = build_graph()
if "history" not in st.session_state:
    st.session_state.history = new_history()

with st.form("request_form"):
    repo = st.text_input("레포 (owner/name)", value="rest8050/pokerogue_test")
    pr_number = st.number_input("PR 번호 (선택, 0이면 없음)", min_value=0, value=0, step=1)
    request = st.text_area("요청", placeholder="예: 이 PR 코드 리뷰해줘")
    submitted = st.form_submit_button("실행")

if submitted:
    initial_state = {
        "request": request,
        "repo": repo,
        "pr_number": pr_number or None,
        "diff": "",
        "readme": "",
        "branches": [],
        "prs": [],
        "ci_logs": [],
        "ci_status": "",
        "pending": [],
        "planned": False,
        "results": {},
        "next": "",
        "final_response": "",
        "history_context": format_recent(st.session_state.history),
    }

    status_box = st.status("실행 중...", expanded=True)
    visited: list[str] = []
    final_state = None
    error: Exception | None = None
    try:
        for step in st.session_state.graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_output in step.items():
                status_box.write(f"완료: {node_name}")
                visited.append(node_name)
                final_state = node_output
    except Exception as exc:
        error = exc

    if error is not None:
        status_box.update(label="오류 발생", state="error")
        st.error(f"실행 중 오류가 발생했습니다: {error}")
        record_turn(
            st.session_state.history,
            request=request,
            repo=repo,
            pr_number=pr_number or None,
            executed_nodes=visited,
            final_response="",
            error=str(error),
        )
    else:
        status_box.update(label="완료", state="complete")
        final_response = (final_state or {}).get("final_response", "")
        if final_response:
            st.markdown(final_response)
        else:
            st.warning("결과를 생성하지 못했습니다.")
        record_turn(
            st.session_state.history,
            request=request,
            repo=repo,
            pr_number=pr_number or None,
            executed_nodes=visited,
            final_response=final_response,
        )

if st.session_state.history:
    with st.expander(f"최근 대화 기록 ({len(st.session_state.history)}개, 오류 보고/문서화용)"):
        for i, turn in enumerate(reversed(st.session_state.history), 1):
            st.markdown(f"**{i}. {turn['request']}** — {turn['repo']}" + (f" #{turn['pr_number']}" if turn["pr_number"] else ""))
            if turn["error"]:
                st.error(turn["error"])
            else:
                st.caption(f"실행: {', '.join(turn['executed_nodes']) or '없음'}")
                st.markdown(turn["final_response"])
            st.divider()
