from backend.app.conversation_store import ConversationStore


def test_messages_are_isolated_by_agent_and_persist_after_reopen(tmp_path):
    db_path = tmp_path / "conversations.db"
    store = ConversationStore(str(db_path))

    store.append("Workmate AI", "user", "오늘 업무 브리핑해줘")
    store.append("Workmate AI", "assistant", "브리핑을 준비하겠습니다.")
    store.append("Game Q&A", "user", "초보자 추천 캐릭터는?")

    assert [message["content"] for message in store.list_messages("Workmate AI")] == [
        "오늘 업무 브리핑해줘",
        "브리핑을 준비하겠습니다.",
    ]
    assert [message["content"] for message in store.list_messages("Game Q&A")] == [
        "초보자 추천 캐릭터는?",
    ]

    reopened = ConversationStore(str(db_path))
    assert len(reopened.list_messages("Workmate AI")) == 2
