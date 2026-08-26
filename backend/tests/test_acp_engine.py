"""Integration tests for the AcpEngine facade."""

from app.core.acp import AcpEngine, AcpError, CompressResult, DecompressResult, SearchResult


def test_compress_decompress_round_trip_restores_original() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "alpha"), ("m2", "beta"), ("m3", "gamma")])
    result = engine.compress(0, 2, "summary of alpha beta gamma")
    assert isinstance(result, CompressResult)
    assert result.tier == 1
    assert result.removed_block_ids == (1, 2, 3)
    assert engine.blocks() == (engine.get_block(result.summary_block_id),)
    restored = engine.decompress(result.summary_block_id)
    assert isinstance(restored, DecompressResult)
    assert restored.restored_block_ids == (1, 2, 3)
    assert [block.content for block in engine.blocks()] == ["alpha", "beta", "gamma"]


def test_compress_invalid_range_returns_structured_error() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "alpha")])
    result = engine.compress(1, 2, "summary")
    assert isinstance(result, AcpError)
    assert result.code == "invalid_range"
    result = engine.compress(2, 1, "summary")
    assert isinstance(result, AcpError)
    assert result.code == "invalid_range"
    result = engine.compress(-1, 0, "summary")
    assert isinstance(result, AcpError)
    assert result.code == "invalid_range"


def test_compress_single_message_block() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "alpha"), ("m2", "beta")])
    result = engine.compress(1, 1, "beta summary")
    assert isinstance(result, CompressResult)
    assert result.removed_block_ids == (2,)
    assert [block.message_id for block in engine.blocks()] == ["m1", "acp_summary_1"]


def test_compress_range_with_skipped_block_returns_error() -> None:
    engine = AcpEngine()
    engine.add_message("m1", "system instruction", skip=True)
    engine.add_message("m2", "user message")
    result = engine.compress(0, 1, "summary")
    assert isinstance(result, AcpError)
    assert result.code == "block_skipped"


def test_compress_empty_content_block() -> None:
    engine = AcpEngine()
    engine.add_message("m1", "")
    engine.add_message("m2", "beta")
    result = engine.compress(0, 1, "summary")
    assert isinstance(result, CompressResult)
    assert result.removed_block_ids == (1, 2)


def test_decompress_non_summary_block_returns_error() -> None:
    engine = AcpEngine()
    engine.add_message("m1", "alpha")
    result = engine.decompress(1)
    assert isinstance(result, AcpError)
    assert result.code == "not_a_summary"


def test_decompress_missing_block_returns_error() -> None:
    engine = AcpEngine()
    result = engine.decompress(99)
    assert isinstance(result, AcpError)
    assert result.code == "block_not_found"


def test_compress_search_decompress_closed_loop() -> None:
    engine = AcpEngine()
    engine.add_messages(
        [("m1", "退款政策 refund policy"), ("m2", "发货时间 shipping schedule")]
    )
    result = engine.compress(0, 1, "历史消息摘要：退款与发货")
    assert isinstance(result, CompressResult)
    search = engine.search_context("退款")
    assert isinstance(search, SearchResult)
    assert search.matched
    assert search.hits[0].block_id == result.summary_block_id
    restored = engine.decompress(result.summary_block_id)
    assert isinstance(restored, DecompressResult)
    assert [block.content for block in engine.blocks()] == [
        "退款政策 refund policy",
        "发货时间 shipping schedule",
    ]


def test_search_hits_hidden_original_content() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "量子纠缠实验数据"), ("m2", "普通对话内容")])
    result = engine.compress(0, 1, "历史消息摘要")
    assert isinstance(result, CompressResult)
    search = engine.search_context("量子纠缠")
    assert isinstance(search, SearchResult)
    assert search.matched
    assert search.hits[0].block_id == result.summary_block_id
    assert search.hits[0].source == "hidden"


def test_nudge_via_engine() -> None:
    engine = AcpEngine()
    assert engine.nudge(1000) is None
    recommendation = engine.nudge(int(128000 * 0.8))
    assert recommendation is not None
    assert recommendation.level == "normal"


def test_status_via_engine() -> None:
    engine = AcpEngine()
    engine.add_messages([("m1", "alpha"), ("m2", "beta")])
    engine.compress(0, 1, "summary")
    status = engine.status()
    assert status.total_blocks == 1
    assert status.ledger_balance >= 0


def test_ledger_never_negative_across_multiple_compressions() -> None:
    """Regression for upstream issue #54: mixed estimates must not drive the ledger negative."""

    class ErraticMeter:
        def __init__(self) -> None:
            self._calls = 0

        def estimate_tokens(self, text: str) -> int:
            self._calls += 1
            return 10 if self._calls % 2 else 100000

    engine = AcpEngine(meter=ErraticMeter())
    engine.add_messages([(f"m{i}", f"message content {i}") for i in range(6)])
    for _ in range(3):
        result = engine.compress(0, 1, "summary")
        assert isinstance(result, CompressResult)
        assert result.ledger_balance >= 0
        restored = engine.decompress(result.summary_block_id)
        assert isinstance(restored, DecompressResult)
        assert restored.ledger_balance >= 0
    assert engine.ledger.never_negative