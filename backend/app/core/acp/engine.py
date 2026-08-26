"""Orchestration of the four ACP operations.

compress replaces a block range with a caller-provided summary text (the
kernel never calls an LLM), decompress restores hidden original content,
search_context performs lexical retrieval, and status reports the
compression ledger.
"""

import time
from dataclasses import dataclass
from typing import Sequence

from .blocks import Block, BlockStore
from .checkpoint import CheckpointRecord, CheckpointStore
from .config import AcpConfig
from .nudge import NudgeRecommendation, evaluate_pressure
from .pricing import AcpLedger, TokenMeter
from .search import SearchHit, search_blocks
from .status import BlockLedgerEntry, CheckpointMappingEntry, ContextStatus


@dataclass(frozen=True)
class AcpError:
    """Structured error returned instead of raising."""

    code: str
    message: str
    detail: dict[str, object] | None = None


@dataclass(frozen=True)
class CompressResult:
    """Outcome of a successful compress operation."""

    summary_block_id: int
    checkpoint_id: int
    tier: int
    removed_block_ids: tuple[int, ...]
    token_delta: int
    ledger_balance: int


@dataclass(frozen=True)
class DecompressResult:
    """Outcome of a successful decompress operation."""

    restored_block_ids: tuple[int, ...]
    checkpoint_id: int
    ledger_balance: int


@dataclass(frozen=True)
class SearchResult:
    """Outcome of a search_context operation."""

    query: str
    hits: tuple[SearchHit, ...]
    total: int
    truncated: bool
    matched: bool


class AcpEngine:
    """Framework-agnostic ACP compression kernel facade."""

    def __init__(self, config: AcpConfig | None = None, meter: TokenMeter | None = None) -> None:
        self._config = config or AcpConfig()
        self._store = BlockStore()
        self._checkpoints = CheckpointStore()
        self._meter = meter
        self._ledger = AcpLedger(meter=meter)

    # -- ingestion -----------------------------------------------------

    def add_message(self, message_id: str, content: str, *, skip: bool = False) -> Block:
        """Add one message as a single atomic block."""
        return self._store.add(message_id, content, skip=skip)

    def add_messages(self, messages: Sequence[tuple[str, str]]) -> list[Block]:
        """Add ``(message_id, content)`` pairs, one block per message."""
        return self._store.add_many(messages)

    def get_block(self, block_id: int) -> Block | None:
        """Look up a block by id, or ``None`` when absent."""
        return self._store.get(block_id)

    def blocks(self) -> tuple[Block, ...]:
        """Current ordered blocks (visible state)."""
        return self._store.all()

    # -- operations ----------------------------------------------------

    def compress(self, seq_start: int, seq_end: int, summary_text: str) -> CompressResult | AcpError:
        """Replace the block range ``[seq_start, seq_end]`` with a summary.

        The summary text is provided by the caller (the model); the kernel
        never calls an LLM. Compressing a single summary block again
        distills it to the next tier. Returns a structured error for
        invalid ranges, skipped blocks, or tier exhaustion.
        """
        blocks = self._store.all()
        if seq_start < 0 or seq_end < seq_start or seq_end >= len(blocks):
            return AcpError(
                code="invalid_range",
                message=f"range [{seq_start}, {seq_end}] out of bounds for {len(blocks)} blocks",
                detail={"seq_start": seq_start, "seq_end": seq_end, "total_blocks": len(blocks)},
            )
        target = self._store.slice(seq_start, seq_end)
        if any(block.skip for block in target):
            return AcpError(
                code="block_skipped",
                message="range contains explicitly skipped blocks",
                detail={"skipped_block_ids": [block.block_id for block in target if block.skip]},
            )
        if len(target) == 1 and target[0].is_summary:
            tier = target[0].tier + 1
            if tier > self._config.max_tier:
                return AcpError(
                    code="tier_limit",
                    message=f"block already at max tier {self._config.max_tier}",
                    detail={"block_id": target[0].block_id, "tier": target[0].tier},
                )
        else:
            tier = 1
        checkpoint_id = self._checkpoints.next_id()
        summary_block = Block(
            block_id=self._store.next_id(),
            message_id=f"acp_summary_{checkpoint_id}",
            content=summary_text,
            tier=tier,
            is_summary=True,
            checkpoint_id=checkpoint_id,
        )
        removed = self._store.replace(seq_start, seq_end, summary_block)
        removed_tokens = self._ledger.estimate("".join(block.content for block in removed))
        summary_tokens = self._ledger.estimate(summary_text)
        source = "meter" if self._meter is not None else "estimate"
        self._ledger.credit("compress", removed_tokens, source=source)
        self._ledger.debit("compress", summary_tokens, source=source)
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            seq_start=seq_start,
            seq_end=seq_end,
            summary_block_id=summary_block.block_id,
            tier=tier,
            original_blocks=tuple(removed),
            token_delta=removed_tokens - summary_tokens,
            created_at=time.time(),
        )
        self._checkpoints.add(record)
        return CompressResult(
            summary_block_id=summary_block.block_id,
            checkpoint_id=checkpoint_id,
            tier=tier,
            removed_block_ids=tuple(block.block_id for block in removed),
            token_delta=removed_tokens - summary_tokens,
            ledger_balance=self._ledger.balance,
        )

    def decompress(self, block_id: int) -> DecompressResult | AcpError:
        """Restore the hidden original content of a summary block.

        The summary block is replaced in place by its original blocks read
        from the checkpoint; checkpoint records are never deleted, so the
        operation stays traceable and repeatable.
        """
        block = self._store.get(block_id)
        if block is None:
            return AcpError(
                code="block_not_found",
                message=f"block {block_id} not found",
                detail={"block_id": block_id},
            )
        if not block.is_summary or block.checkpoint_id is None:
            return AcpError(
                code="not_a_summary",
                message=f"block {block_id} is not a compressed summary block",
                detail={"block_id": block_id},
            )
        record = self._checkpoints.get(block.checkpoint_id)
        if record is None:
            return AcpError(
                code="checkpoint_missing",
                message=f"checkpoint {block.checkpoint_id} missing",
                detail={"checkpoint_id": block.checkpoint_id},
            )
        removed = self._store.replace_by_id(block_id, record.original_blocks)
        assert removed is not None
        restored_tokens = self._ledger.estimate(
            "".join(original.content for original in record.original_blocks)
        )
        summary_tokens = self._ledger.estimate(block.content)
        source = "meter" if self._meter is not None else "estimate"
        self._ledger.debit("decompress", restored_tokens, source=source)
        self._ledger.credit("decompress", summary_tokens, source=source)
        return DecompressResult(
            restored_block_ids=tuple(original.block_id for original in record.original_blocks),
            checkpoint_id=record.checkpoint_id,
            ledger_balance=self._ledger.balance,
        )

    def search_context(self, query: str, top_k: int | None = None) -> SearchResult:
        """Lexically retrieve blocks matching ``query``.

        Both visible block content and hidden checkpointed content are
        searched; hits link back to their blocks so the caller can
        decompress them for details. An empty query match returns an empty
        result with ``matched=False`` instead of raising.
        """
        limit = top_k if top_k is not None else self._config.search_top_k
        hidden_texts = {
            record.summary_block_id: "".join(block.content for block in record.original_blocks)
            for record in self._checkpoints.all()
        }
        all_hits = search_blocks(
            self._store.all(),
            query,
            min_score=self._config.search_min_score,
            ngram_size=self._config.search_ngram_size,
            hidden_texts=hidden_texts,
        )
        hits = all_hits[:limit]
        return SearchResult(
            query=query,
            hits=tuple(hits),
            total=len(all_hits),
            truncated=len(all_hits) > limit,
            matched=bool(all_hits),
        )

    def status(self) -> ContextStatus:
        """Report the context breakdown, block ledger, and checkpoint mapping."""
        blocks = self._store.all()
        tier_counts: dict[int, int] = {}
        for block in blocks:
            tier_counts[block.tier] = tier_counts.get(block.tier, 0) + 1
        return ContextStatus(
            total_blocks=len(blocks),
            total_chars=sum(len(block.content) for block in blocks),
            summary_blocks=sum(1 for block in blocks if block.is_summary),
            original_blocks=sum(1 for block in blocks if not block.is_summary),
            tier_counts=tier_counts,
            ledger_balance=self._ledger.balance,
            ledger_warnings=self._ledger.warnings,
            blocks=tuple(
                BlockLedgerEntry(
                    block_id=block.block_id,
                    message_id=block.message_id,
                    tier=block.tier,
                    is_summary=block.is_summary,
                    content_length=len(block.content),
                )
                for block in blocks
            ),
            checkpoints=tuple(
                CheckpointMappingEntry(
                    checkpoint_id=record.checkpoint_id,
                    seq_start=record.seq_start,
                    seq_end=record.seq_end,
                    summary_block_id=record.summary_block_id,
                    tier=record.tier,
                )
                for record in self._checkpoints.all()
            ),
        )

    def nudge(self, current_tokens: int) -> NudgeRecommendation | None:
        """Evaluate context pressure; advisory only, never mandatory."""
        return evaluate_pressure(current_tokens, self._config)

    # -- introspection -------------------------------------------------

    @property
    def config(self) -> AcpConfig:
        return self._config

    @property
    def ledger(self) -> AcpLedger:
        return self._ledger