from video_draft_pipeline.a2a_server.tasks import TaskStore


def test_create_returns_submitted_record_with_unique_ids_and_context_id():
    store = TaskStore()

    first = store.create()
    second = store.create()

    assert first.state == "TASK_STATE_SUBMITTED"
    assert first.answer is None
    assert first.task_id != second.task_id
    assert first.context_id
    assert first.context_id != second.context_id


def test_mark_working_updates_state():
    store = TaskStore()
    record = store.create()

    store.mark_working(record.task_id)

    assert store.get(record.task_id).state == "TASK_STATE_WORKING"


def test_get_returns_none_for_unknown_task_id():
    store = TaskStore()

    assert store.get("does-not-exist") is None


def test_get_returns_the_stored_record():
    store = TaskStore()
    record = store.create()

    assert store.get(record.task_id) is record


def test_mark_completed_updates_state_answer_and_output_video_url():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "영상이 완성되었습니다.", output_video_url="http://x/media/p.mp4")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_COMPLETED"
    assert updated.answer == "영상이 완성되었습니다."
    assert updated.output_video_url == "http://x/media/p.mp4"


def test_mark_completed_output_video_url_defaults_to_none():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "완료")

    assert store.get(record.task_id).output_video_url is None


def test_mark_completed_sets_artifact_id():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "완료", output_video_url="http://x/p.mp4")

    assert store.get(record.task_id).artifact_id


def test_mark_completed_does_not_change_artifact_id_across_repeated_reads():
    store = TaskStore()
    record = store.create()

    store.mark_completed(record.task_id, "완료", output_video_url="http://x/p.mp4")
    first_read = store.get(record.task_id).artifact_id
    second_read = store.get(record.task_id).artifact_id

    assert first_read == second_read


def test_mark_input_required_sets_artifact_id():
    store = TaskStore()
    record = store.create()

    store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    assert store.get(record.task_id).artifact_id


def test_mark_failed_updates_state_and_answer():
    store = TaskStore()
    record = store.create()

    store.mark_failed(record.task_id, "실패했습니다.")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_FAILED"
    assert updated.answer == "실패했습니다."


def test_mark_input_required_updates_state_and_answer():
    store = TaskStore()
    record = store.create()

    store.mark_input_required(record.task_id, "일부 장면에 수동 수정이 필요합니다")

    updated = store.get(record.task_id)
    assert updated.state == "TASK_STATE_INPUT_REQUIRED"
    assert updated.answer == "일부 장면에 수동 수정이 필요합니다"


def test_request_cancel_sets_flag_and_canceled_state():
    store = TaskStore()
    record = store.create()

    store.request_cancel(record.task_id)

    updated = store.get(record.task_id)
    assert updated.cancel_requested is True
    assert updated.state == "TASK_STATE_CANCELED"


def test_create_returns_record_with_cancel_requested_false():
    store = TaskStore()

    record = store.create()

    assert record.cancel_requested is False


def test_set_project_id_updates_record():
    store = TaskStore()
    record = store.create()

    store.set_project_id(record.task_id, "proj_abc123")

    assert store.get(record.task_id).project_id == "proj_abc123"


def test_set_unresolved_scenes_updates_record():
    store = TaskStore()
    record = store.create()
    scenes = [{"sceneId": "scene_04", "imageUrl": "http://x/cand_1.png", "issues": ["too wide"]}]

    store.set_unresolved_scenes(record.task_id, scenes)

    assert store.get(record.task_id).unresolved_scenes == scenes


def test_register_message_id_and_lookup():
    store = TaskStore()
    record = store.create()

    store.register_message_id("msg-001", record.task_id)

    assert store.task_id_for_message("msg-001") == record.task_id


def test_task_id_for_message_returns_none_when_unseen():
    store = TaskStore()

    assert store.task_id_for_message("never-sent") is None


def test_claim_message_id_first_call_claims_and_returns_true_none():
    store = TaskStore()

    claimed, existing = store.claim_message_id("m1")

    assert claimed is True
    assert existing is None


def test_claim_message_id_second_call_before_resolution_returns_false_none():
    store = TaskStore()
    store.claim_message_id("m1")

    claimed, existing = store.claim_message_id("m1")

    assert claimed is False
    assert existing is None


def test_claim_message_id_after_register_returns_false_and_task_id():
    store = TaskStore()
    store.claim_message_id("m1")
    record = store.create()
    store.register_message_id("m1", record.task_id)

    claimed, existing = store.claim_message_id("m1")

    assert claimed is False
    assert existing == record.task_id


def test_release_message_id_allows_reclaiming():
    store = TaskStore()
    store.claim_message_id("m1")

    store.release_message_id("m1")
    claimed, existing = store.claim_message_id("m1")

    assert claimed is True
    assert existing is None


def test_release_message_id_is_a_no_op_when_unclaimed():
    store = TaskStore()

    store.release_message_id("never-claimed")
