import pytest

from video_draft_pipeline.a2a_server.protocol import (
    ProtocolError,
    TaskState,
    build_artifact,
    build_task_response,
    build_unresolved_artifact,
    build_video_artifact,
    extract_text,
    parse_message_send_request,
)


def test_task_state_values_match_the_doc_exactly():
    assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
    assert TaskState.WORKING.value == "TASK_STATE_WORKING"
    assert TaskState.INPUT_REQUIRED.value == "TASK_STATE_INPUT_REQUIRED"
    assert TaskState.AUTH_REQUIRED.value == "TASK_STATE_AUTH_REQUIRED"
    assert TaskState.COMPLETED.value == "TASK_STATE_COMPLETED"
    assert TaskState.FAILED.value == "TASK_STATE_FAILED"
    assert TaskState.CANCELED.value == "TASK_STATE_CANCELED"
    assert TaskState.REJECTED.value == "TASK_STATE_REJECTED"


def test_parse_message_send_request_extracts_valid_envelope():
    body = {
        "message": {
            "messageId": "msg-001",
            "role": "ROLE_USER",
            "parts": [{"text": "할로윈 이벤트 영상 만들어줘", "mediaType": "text/plain"}],
        },
        "metadata": {"request_id": "req-001"},
    }

    message = parse_message_send_request(body)

    assert message.messageId == "msg-001"
    assert message.role == "ROLE_USER"
    assert message.parts[0].text == "할로윈 이벤트 영상 만들어줘"


def test_parse_message_send_request_rejects_missing_message():
    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request({})

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_parse_message_send_request_rejects_missing_message_id():
    body = {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"
    assert "messageId" in exc_info.value.message


def test_parse_message_send_request_rejects_wrong_role():
    body = {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "hi"}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_parse_message_send_request_rejects_empty_parts():
    body = {"message": {"messageId": "m", "role": "ROLE_USER", "parts": []}}

    with pytest.raises(ProtocolError):
        parse_message_send_request(body)


def test_parse_message_send_request_rejects_part_with_wrong_field_type():
    body = {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": 123}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_parse_message_send_request_rejects_bad_part_type_when_mixed_with_non_dict_entries():
    body = {"message": {"messageId": "m", "role": "ROLE_USER", "parts": ["not-a-dict", {"text": 123}]}}

    with pytest.raises(ProtocolError) as exc_info:
        parse_message_send_request(body)

    assert exc_info.value.status == "INVALID_ARGUMENT"


def test_extract_text_joins_text_parts_and_skips_data_only_parts():
    body = {
        "message": {
            "messageId": "m",
            "role": "ROLE_USER",
            "parts": [{"text": "안녕"}, {"data": {"foo": "bar"}}, {"text": "만들어줘"}],
        }
    }
    message = parse_message_send_request(body)

    assert extract_text(message) == "안녕\n만들어줘"


def test_build_artifact_shape():
    artifact = build_artifact("artifact-1", "결과", [{"text": "hi", "mediaType": "text/plain"}])

    assert artifact == {
        "artifactId": "artifact-1",
        "name": "결과",
        "parts": [{"text": "hi", "mediaType": "text/plain"}],
    }


def test_build_video_artifact_includes_markdown_and_json_parts():
    artifact = build_video_artifact("artifact-1", "영상이 완성되었습니다.", "http://x/media/p.mp4")

    assert artifact["artifactId"] == "artifact-1"
    assert artifact["name"] == "영상 초안 결과"
    assert artifact["parts"][0] == {"text": "영상이 완성되었습니다.", "mediaType": "text/markdown"}
    assert artifact["parts"][1] == {
        "data": {"output_video_url": "http://x/media/p.mp4"},
        "mediaType": "application/json",
    }


def test_build_video_artifact_omits_json_part_when_no_url():
    artifact = build_video_artifact("artifact-1", "실패했습니다.", None)

    assert len(artifact["parts"]) == 1


def test_build_unresolved_artifact_shape():
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand.png", "issues": ["too wide"]}]

    artifact = build_unresolved_artifact("artifact-1", scenes)

    assert artifact["artifactId"] == "artifact-1"
    assert artifact["parts"] == [{"data": {"unresolvedScenes": scenes}, "mediaType": "application/json"}]


def test_build_task_response_minimal():
    response = build_task_response("task-1", "ctx-1", TaskState.WORKING.value)

    assert response == {
        "task": {"id": "task-1", "contextId": "ctx-1", "status": {"state": "TASK_STATE_WORKING"}}
    }


def test_build_task_response_includes_answer_message():
    response = build_task_response("task-1", "ctx-1", TaskState.COMPLETED.value, answer="완료")

    assert response["task"]["status"]["message"] == {"parts": [{"text": "완료"}]}


def test_build_task_response_appends_detail_as_a_second_message_part():
    response = build_task_response(
        "task-1", "ctx-1", TaskState.FAILED.value, answer="영상 생성에 실패했습니다: boom", detail="Traceback ..."
    )

    assert response["task"]["status"]["message"] == {"parts": [{"text": "영상 생성에 실패했습니다: boom"}, {"text": "Traceback ..."}]}


def test_build_task_response_omits_detail_part_when_none():
    response = build_task_response("task-1", "ctx-1", TaskState.FAILED.value, answer="영상 생성에 실패했습니다: boom")

    assert response["task"]["status"]["message"] == {"parts": [{"text": "영상 생성에 실패했습니다: boom"}]}


def test_build_task_response_includes_unresolved_scenes_and_artifacts():
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand.png", "issues": []}]
    artifacts = [build_unresolved_artifact("artifact-1", scenes)]

    response = build_task_response(
        "task-1", "ctx-1", TaskState.INPUT_REQUIRED.value,
        answer="일부 장면에 수동 수정이 필요합니다", unresolved_scenes=scenes, artifacts=artifacts,
    )

    assert response["task"]["status"]["unresolvedScenes"] == scenes
    assert response["task"]["artifacts"] == artifacts


def test_build_task_response_omits_artifacts_key_when_none():
    response = build_task_response("task-1", "ctx-1", TaskState.WORKING.value)

    assert "artifacts" not in response["task"]
