"""Tests for shadow-price accounting with an injectable token meter."""

from app.core.acp.pricing import AcpLedger, TokenMeter


class FixedMeter:
    """Mock meter returning a fixed token count per call."""

    def __init__(self, tokens: int) -> None:
        self._tokens = tokens
        self.calls = 0

    def estimate_tokens(self, text: str) -> int:
        self.calls += 1
        return self._tokens


def test_credit_increases_balance() -> None:
    ledger = AcpLedger()
    entry = ledger.credit("compress", 100)
    assert entry.balance == 100
    assert ledger.balance == 100


def test_debit_decreases_balance() -> None:
    ledger = AcpLedger(initial_balance=100)
    entry = ledger.debit("decompress", 40)
    assert entry.balance == 60
    assert ledger.balance == 60


def test_debit_never_drives_balance_negative() -> None:
    ledger = AcpLedger(initial_balance=10)
    entry = ledger.debit("decompress", 500)
    assert entry.balance == 0
    assert ledger.balance == 0
    assert entry.source == "clamped"
    assert entry.warning is not None
    assert ledger.warnings


def test_never_negative_across_mixed_operations() -> None:
    ledger = AcpLedger(initial_balance=50)
    ledger.credit("compress", 200)
    ledger.debit("decompress", 1000)
    ledger.credit("compress", 30)
    ledger.debit("decompress", 9999)
    assert ledger.never_negative
    assert ledger.balance == 0
    assert len(ledger.warnings) == 2


def test_injected_meter_values_are_used() -> None:
    meter: TokenMeter = FixedMeter(42)
    ledger = AcpLedger(meter=meter)
    assert ledger.estimate("any text") == 42
    assert meter.calls == 1


def test_fallback_estimate_without_meter() -> None:
    ledger = AcpLedger()
    assert ledger.estimate("") == 1
    assert ledger.estimate("abcd") == 1
    assert ledger.estimate("abcdefgh") == 2


def test_entries_are_recorded_in_order() -> None:
    ledger = AcpLedger(initial_balance=10)
    ledger.credit("compress", 5)
    ledger.debit("decompress", 3)
    entries = ledger.entries
    assert [entry.operation for entry in entries] == ["compress", "decompress"]
    assert [entry.balance for entry in entries] == [15, 12]


def test_negative_charges_are_clamped_to_zero() -> None:
    ledger = AcpLedger(initial_balance=10)
    ledger.credit("compress", -5)
    assert ledger.balance == 10
    ledger.debit("decompress", -5)
    assert ledger.balance == 10