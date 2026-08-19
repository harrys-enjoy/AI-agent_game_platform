from app.conversation_store import ConversationStore


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


def test_messages_are_isolated_by_owner_and_agent(tmp_path):
    store = ConversationStore(str(tmp_path / "owner-conversations.db"))

    store.append("Workmate AI", "user", "owner-a message", owner="Owner A")
    store.append("Workmate AI", "user", "owner-b message", owner="Owner B")

    assert [item["content"] for item in store.list_messages("Workmate AI", owner="Owner A")] == ["owner-a message"]
    assert [item["content"] for item in store.list_messages("Workmate AI", owner="Owner B")] == ["owner-b message"]
