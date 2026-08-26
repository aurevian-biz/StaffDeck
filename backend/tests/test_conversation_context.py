from types import SimpleNamespace

from app.core.acp import AcpEngine
from app.core.agent_loop import (
    AgentLoop,
    _execute_acp_ops,
    _resolve_compression_mode,
    _restore_acp_engine,
    _serialize_acp_engine,
)
from app.core.conversation_context import (
    LONG_SUMMARY_PREFIX,
    MEDIUM_SUMMARY_PREFIX,
    build_conversation_context,
)
from app.core.harness_agent import _harness_actions_from_raw
from app.llm.client import _fit_request_messages


def test_conversation_context_keeps_full_history_under_budget() -> None:
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好"},
        {"role": "user", "content": "我是 hx，我要买 A2"},
        {"role": "assistant", "content": "请问买几个？"},
        {"role": "user", "content": "买两个"},
    ]

    context = build_conversation_context(messages, token_budget=1_000)

    assert context["messages"] == messages
    assert context["metadata"]["compacted"] is False
    assert context["metadata"]["total_messages"] == 5
    assert context["metadata"]["omitted_messages"] == 0


def test_conversation_context_compacts_only_after_budget_is_exceeded() -> None:
    messages = [
        {"role": "user", "content": f"old user message {index} " + "x" * 80}
        if index % 2 == 0
        else {"role": "assistant", "content": f"old assistant message {index} " + "y" * 80}
        for index in range(20)
    ]

    context = build_conversation_context(messages, token_budget=500)
    projected = context["messages"]

    assert context["metadata"]["compacted"] is True
    assert context["metadata"]["omitted_messages"] > 0
    assert projected[0]["role"] == "user"
    assert "历史的信息可以被总结为" in projected[0]["content"]
    assert "近期的历史信息总结为" in projected[1]["content"]
    assert projected[-1]["content"] == messages[-1]["content"]
    assert context["metadata"]["estimated_tokens"] <= 500


def test_context_rotates_medium_history_into_long_history_on_next_threshold() -> None:
    messages = [
        {
            "id": f"message_{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"round {index} " + ("中" * 120),
            "created_at": f"2026-07-13T12:{index:02d}:00",
        }
        for index in range(20)
    ]
    summaries: list[tuple[str, str]] = []

    def summarize(label: str, source: str, _budget: int) -> str:
        summaries.append((label, source))
        return f"{label}摘要：{source[:120]}"

    first = build_conversation_context(
        messages, token_budget=700, summary_builder=summarize
    )
    first_state = first["context_state"]

    assert first_state["compaction_count"] == 1
    assert first_state["long_term_summary"] == ""
    assert first_state["medium_term_summary"].startswith("近期历史信息摘要")
    assert first["messages"][0]["content"].startswith("历史的信息可以被总结为：")
    assert first["messages"][1]["content"].startswith("近期的历史信息总结为：")

    more_messages = [
        *messages,
        *[
            {
                "id": f"message_{index}",
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"new round {index} " + ("新" * 120),
                "created_at": f"2026-07-13T13:{index - 20:02d}:00",
            }
            for index in range(20, 36)
        ],
    ]
    second = build_conversation_context(
        more_messages,
        token_budget=700,
        context_state=first_state,
        summary_builder=summarize,
    )
    second_state = second["context_state"]

    assert second_state["compaction_count"] == 2
    assert second_state["long_term_summary"].startswith("长期历史信息摘要")
    assert first_state["medium_term_summary"] in summaries[-2][1]
    assert second_state["medium_term_summary"].startswith("近期历史信息摘要")
    assert second["metadata"]["current_turn_time"] == "2026-07-13T13:15:00"
    assert second["metadata"]["estimated_tokens"] <= 700


def test_legacy_mode_keeps_existing_contract_and_shape() -> None:
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好"},
    ]

    context = build_conversation_context(messages, token_budget=1_000)

    assert set(context) == {"messages", "compacted_summary", "context_state", "metadata"}
    assert set(context["context_state"]) == {
        "long_term_summary",
        "medium_term_summary",
        "summarized_through_message_id",
        "compaction_count",
    }
    assert context["messages"] == messages
    assert context["metadata"].get("compression_mode") != "acp"


def test_acp_mode_projects_summary_blocks_with_existing_prefixes() -> None:
    acp_state = {
        "blocks": [
            {
                "block_id": 1,
                "message_id": "acp_summary_1",
                "role": "user",
                "content": "模型书写的长期摘要",
                "tier": 1,
                "is_summary": True,
                "checkpoint_id": 1,
                "skip": False,
            },
            {
                "block_id": 2,
                "message_id": "acp_summary_2",
                "role": "user",
                "content": "模型书写的近期摘要",
                "tier": 1,
                "is_summary": True,
                "checkpoint_id": 2,
                "skip": False,
            },
            {
                "block_id": 3,
                "message_id": "m3",
                "role": "user",
                "content": "最新消息",
                "tier": 1,
                "is_summary": False,
                "checkpoint_id": None,
                "skip": False,
            },
        ],
        "checkpoints": [],
        "roles": {"m3": "user"},
        "ingested_message_ids": ["m1", "m2", "m3"],
        "compaction_count": 1,
    }

    context = build_conversation_context(
        [{"role": "user", "content": "最新消息"}],
        token_budget=1_000,
        context_state={"acp": acp_state},
        compression_mode="acp",
    )
    messages = context["messages"]

    assert messages[0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert messages[1]["content"].startswith(MEDIUM_SUMMARY_PREFIX)
    assert messages[2]["content"] == "最新消息"
    assert context["metadata"]["compression_mode"] == "acp"
    assert context["metadata"]["compacted"] is True
    assert context["compacted_summary"] == "模型书写的长期摘要\n模型书写的近期摘要"


def test_acp_mode_loads_legacy_four_key_state_without_loss() -> None:
    legacy_state = {
        "long_term_summary": "长期摘要",
        "medium_term_summary": "近期摘要",
        "summarized_through_message_id": "message_3",
        "compaction_count": 3,
    }
    messages = [
        {
            "id": f"message_{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"内容 {index}",
        }
        for index in range(8)
    ]

    context = build_conversation_context(
        messages,
        token_budget=1_000,
        context_state=legacy_state,
        compression_mode="acp",
    )
    state = context["context_state"]

    assert state["compaction_count"] == 3
    assert state["long_term_summary"] == "长期摘要"
    assert state["medium_term_summary"] == "近期摘要"
    assert context["messages"][0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert context["messages"][1]["content"].startswith(MEDIUM_SUMMARY_PREFIX)
    assert context["messages"][-1]["content"] == "内容 7"


def test_normalize_state_preserves_unknown_keys() -> None:
    context = build_conversation_context(
        [],
        context_state={"future_key": {"a": 1}, "compaction_count": 2},
        compression_mode="acp",
    )

    assert context["context_state"]["future_key"] == {"a": 1}
    assert context["context_state"]["compaction_count"] == 2


def test_harness_action_parses_acp_ops_attached_field() -> None:
    actions = _harness_actions_from_raw(
        {
            "action": "finish",
            "status": "completed",
            "acp_ops": {"compress": {"seq_start": 0, "seq_end": 2, "summary": "摘要"}},
        }
    )

    assert len(actions) == 1
    assert actions[0].acp_ops == {
        "compress": {"seq_start": 0, "seq_end": 2, "summary": "摘要"}
    }


def test_harness_action_ignores_malformed_acp_ops() -> None:
    actions = _harness_actions_from_raw(
        {"action": "finish", "status": "completed", "acp_ops": "not-a-dict"}
    )

    assert len(actions) == 1
    assert actions[0].acp_ops is None
    assert actions[0].action == "finish"
    assert actions[0].status == "completed"


def test_fit_request_messages_keeps_acp_summary_messages() -> None:
    messages = [
        {"role": "user", "content": f"{LONG_SUMMARY_PREFIX}\n长期摘要内容"},
        {"role": "user", "content": f"{MEDIUM_SUMMARY_PREFIX}\n近期摘要内容"},
        *[
            {"role": "user", "content": f"填充消息 {index} " + "x" * 200}
            for index in range(10)
        ],
        {"role": "user", "content": "最后一条"},
    ]

    fitted = _fit_request_messages(messages, token_budget=200)

    assert fitted[0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert fitted[1]["content"].startswith(MEDIUM_SUMMARY_PREFIX)
    assert fitted[-1]["content"] == "最后一条"


def test_acp_flag_off_forces_legacy_routing() -> None:
    assert _resolve_compression_mode("acp", acp_enabled=False) == "legacy"
    assert _resolve_compression_mode("acp", acp_enabled=True) == "acp"
    assert _resolve_compression_mode("legacy", acp_enabled=True) == "legacy"


def test_context_compression_mode_preference_chain() -> None:
    owner = SimpleNamespace(db=SimpleNamespace(get=lambda _model, _key: None))
    assert AgentLoop._get_context_compression_mode(owner, "tenant_test") == "legacy"

    def get_ui_config(model, _key):
        if model.__name__ == "UIConfig":
            return SimpleNamespace(context_compression_mode="acp")
        return None

    owner = SimpleNamespace(db=SimpleNamespace(get=get_ui_config))
    assert AgentLoop._get_context_compression_mode(owner, "tenant_test") == "acp"

    agent = SimpleNamespace(
        tenant_id="tenant_test",
        status="active",
        metadata_json={"context_compression_mode": "acp"},
    )

    def get_agent_override(model, key):
        if model.__name__ == "AgentProfile" and key == "agent_1":
            return agent
        return SimpleNamespace(context_compression_mode="legacy")

    owner = SimpleNamespace(db=SimpleNamespace(get=get_agent_override))
    assert AgentLoop._get_context_compression_mode(owner, "tenant_test", "agent_1") == "acp"

    def get_invalid(model, _key):
        return SimpleNamespace(context_compression_mode="auto")

    owner = SimpleNamespace(db=SimpleNamespace(get=get_invalid))
    assert AgentLoop._get_context_compression_mode(owner, "tenant_test") == "legacy"


def test_acp_ops_compress_search_decompress_roundtrip() -> None:
    engine = AcpEngine()
    engine.add_messages(
        [
            ("m1", "用户说需要退款 500 元"),
            ("m2", "客服确认订单号 A2"),
            ("m3", "最新消息"),
        ]
    )

    results, ok = _execute_acp_ops(
        engine, [{"compress": {"seq_start": 0, "seq_end": 1, "summary": "用户申请退款，订单号 A2"}}]
    )
    assert ok is True
    assert results[0]["op"] == "compress"
    assert results[0]["success"] is True
    assert len(engine._checkpoints.all()) == 1

    search, ok = _execute_acp_ops(engine, [{"search_context": {"query": "500"}}])
    assert ok is True
    assert search[0]["result"]["matched"] is True
    assert any(hit["source"] == "hidden" for hit in search[0]["result"]["hits"])

    summary_block_id = engine.blocks()[0].block_id
    decompress, ok = _execute_acp_ops(
        engine, [{"decompress": {"block_id": summary_block_id}}]
    )
    assert ok is True
    assert decompress[0]["success"] is True
    assert len(engine.blocks()) == 3


def test_acp_checkpoint_originals_capped_to_most_recent_five() -> None:
    engine = AcpEngine()
    engine.add_messages([(f"m{index}", f"消息内容 {index} " + "x" * 50) for index in range(12)])
    for index in range(6):
        results, ok = _execute_acp_ops(
            engine,
            [{"compress": {"seq_start": 0, "seq_end": 1, "summary": f"摘要 {index}"}}],
        )
        assert ok is True

    state = _serialize_acp_engine(
        engine,
        ingested_message_ids=[f"m{index}" for index in range(12)],
        roles={},
        compaction_count=6,
    )
    checkpoints = state["checkpoints"]

    assert len(checkpoints) == 6
    with_originals = [item for item in checkpoints if item["original_blocks"]]
    assert len(with_originals) == 5
    assert checkpoints[0]["originals_evicted"] is True
    assert checkpoints[0]["original_blocks"] == []


def test_acp_state_restores_engine_for_next_turn() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "第一条"), ("m2", "第二条"), ("m3", "第三条")])
    _execute_acp_ops(
        engine, [{"compress": {"seq_start": 0, "seq_end": 1, "summary": "前两条摘要"}}]
    )
    state = _serialize_acp_engine(
        engine,
        ingested_message_ids=["m1", "m2", "m3"],
        roles={"m1": "user", "m2": "assistant", "m3": "user"},
        compaction_count=1,
    )

    restored = AcpEngine()
    _restore_acp_engine(restored, state)

    assert [block.message_id for block in restored.blocks()] == ["acp_summary_1", "m3"]
    assert restored.blocks()[0].is_summary is True

    context = build_conversation_context(
        [],
        token_budget=1_000,
        context_state={"acp": state},
        compression_mode="acp",
    )
    assert context["messages"][0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert context["messages"][1]["content"] == "第三条"


def test_legacy_mode_preserves_legacy_four_key_state() -> None:
    legacy_state = {
        "long_term_summary": "长期摘要",
        "medium_term_summary": "近期摘要",
        "summarized_through_message_id": "message_3",
        "compaction_count": 3,
    }
    messages = [
        {
            "id": f"message_{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"内容 {index}",
        }
        for index in range(8)
    ]

    context = build_conversation_context(
        messages, token_budget=1_000, context_state=legacy_state
    )
    state = context["context_state"]

    assert state["compaction_count"] == 3
    assert state["long_term_summary"] == "长期摘要"
    assert state["medium_term_summary"] == "近期摘要"
    assert context["messages"][0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert context["messages"][1]["content"].startswith(MEDIUM_SUMMARY_PREFIX)
    assert context["messages"][-1]["content"] == "内容 7"


def test_invalid_context_state_falls_back_to_empty_state() -> None:
    messages = [{"role": "user", "content": "你好"}]
    for bad_state in (
        None,
        "not-a-dict",
        42,
        {"acp": "not-a-dict"},
        {"acp": {"blocks": "bad"}},
    ):
        context = build_conversation_context(
            messages,
            context_state=bad_state,  # type: ignore[arg-type]
            compression_mode="acp",
        )
        state = context["context_state"]
        assert state["compaction_count"] == 0
        assert state["long_term_summary"] == ""
        assert context["messages"][-1]["content"] == "你好"


def test_legacy_mode_skips_summary_prefixed_messages_when_compacting() -> None:
    messages = [
        {"id": "m1", "role": "user", "content": f"{LONG_SUMMARY_PREFIX}\n历史摘要内容"},
        {"id": "m2", "role": "user", "content": f"{MEDIUM_SUMMARY_PREFIX}\n近期摘要内容"},
        *[
            {
                "id": f"m{index}",
                "role": "user",
                "content": f"普通消息 {index} " + "x" * 120,
            }
            for index in range(3, 15)
        ],
    ]

    context = build_conversation_context(messages, token_budget=300)
    state = context["context_state"]

    assert state["compaction_count"] == 1
    assert "历史摘要内容" not in state["medium_term_summary"]
    assert "近期摘要内容" not in state["medium_term_summary"]
    assert state["summarized_through_message_id"] == "m8"


def test_acp_switch_back_preserves_checkpoints_and_merges_new_messages() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "第一条"), ("m2", "第二条"), ("m3", "第三条")])
    _execute_acp_ops(
        engine, [{"compress": {"seq_start": 0, "seq_end": 1, "summary": "前两条摘要"}}]
    )
    acp_state = _serialize_acp_engine(
        engine,
        ingested_message_ids=["m1", "m2", "m3"],
        roles={"m1": "user", "m2": "assistant", "m3": "user"},
        compaction_count=1,
    )
    context_state = {"acp": acp_state}

    # Legacy 期间：acp 子状态与 checkpoint 保留不清理。
    legacy_context = build_conversation_context(
        [
            {"id": "m1", "role": "user", "content": "第一条"},
            {"id": "m2", "role": "assistant", "content": "第二条"},
            {"id": "m3", "role": "user", "content": "第三条"},
        ],
        token_budget=1_000,
        context_state=context_state,
    )
    assert legacy_context["context_state"]["acp"] == acp_state

    # 切回 ACP：恢复引擎与 checkpoint，legacy 期间的新消息合并为新块。
    loop = object.__new__(AgentLoop)
    loop.db = SimpleNamespace(
        get=lambda _model, _key: None,
        exec=lambda _stmt: SimpleNamespace(first=lambda: None),
    )
    chat_session = SimpleNamespace(
        id="session_1",
        tenant_id="tenant_test",
        agent_id=None,
        context_state_json=context_state,
    )
    context = loop._acp_conversation_context(
        chat_session,
        [
            {"id": "m1", "role": "user", "content": "第一条"},
            {"id": "m2", "role": "assistant", "content": "第二条"},
            {"id": "m3", "role": "user", "content": "第三条"},
            {"id": "m4", "role": "user", "content": "第四条"},
        ],
        model_config=None,
    )
    messages = context["messages"]

    assert messages[0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert messages[1]["content"] == "第三条"
    assert messages[2]["content"] == "第四条"
    next_acp = context["context_state"]["acp"]
    assert len(next_acp["checkpoints"]) == 1
    assert "m4" in next_acp["ingested_message_ids"]


def test_fit_request_messages_keeps_mixed_legacy_and_acp_summaries() -> None:
    messages = [
        {"role": "user", "content": f"{LONG_SUMMARY_PREFIX}\n长期摘要内容"},
        {"role": "user", "content": f"{MEDIUM_SUMMARY_PREFIX}\n近期摘要内容"},
        {"role": "user", "content": f"{LONG_SUMMARY_PREFIX}\nACP 摘要块内容"},
        *[
            {"role": "user", "content": f"填充消息 {index} " + "x" * 200}
            for index in range(10)
        ],
        {"role": "user", "content": "最后一条"},
    ]

    fitted = _fit_request_messages(messages, token_budget=200)

    assert fitted[0]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert fitted[1]["content"].startswith(MEDIUM_SUMMARY_PREFIX)
    assert fitted[2]["content"].startswith(LONG_SUMMARY_PREFIX)
    assert fitted[-1]["content"] == "最后一条"
