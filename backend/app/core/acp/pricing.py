"""Shadow-price accounting with an injectable token meter.

The kernel never assumes it knows the host's token pricing: callers inject
a meter backed by real usage accounting (upstream issue #54). The ledger
defensively clamps debits so the balance can never go negative, and flags
a warning whenever clamping occurs.
"""

from dataclasses import dataclass
from typing import Protocol


class TokenMeter(Protocol):
    """Injected token meter; the caller provides real usage accounting."""

    def estimate_tokens(self, text: str) -> int: ...


@dataclass(frozen=True)
class LedgerEntry:
    """One accounting operation on the ledger."""

    operation: str
    tokens: int
    balance: int
    source: str
    warning: str | None = None


class AcpLedger:
    """Token ledger whose balance is guaranteed never to go negative."""

    def __init__(self, meter: TokenMeter | None = None, initial_balance: int = 0) -> None:
        self._meter = meter
        self._balance = max(0, initial_balance)
        self._entries: list[LedgerEntry] = []
        self._warnings: list[str] = []

    def estimate(self, text: str) -> int:
        """Estimate tokens for ``text`` via the injected meter, or a fallback."""
        if self._meter is not None:
            return max(0, self._meter.estimate_tokens(text))
        return max(1, (len(text) + 3) // 4)

    def credit(self, operation: str, tokens: int, source: str = "meter") -> LedgerEntry:
        tokens = max(0, tokens)
        self._balance += tokens
        entry = LedgerEntry(
            operation=operation,
            tokens=tokens,
            balance=self._balance,
            source=source,
        )
        self._entries.append(entry)
        return entry

    def debit(self, operation: str, tokens: int, source: str = "meter") -> LedgerEntry:
        tokens = max(0, tokens)
        if tokens > self._balance:
            warning = f"debit of {tokens} exceeds balance {self._balance}; clamped to 0"
            self._warnings.append(warning)
            entry = LedgerEntry(
                operation=operation,
                tokens=self._balance,
                balance=0,
                source="clamped",
                warning=warning,
            )
            self._balance = 0
        else:
            self._balance -= tokens
            entry = LedgerEntry(
                operation=operation,
                tokens=tokens,
                balance=self._balance,
                source=source,
            )
        self._entries.append(entry)
        return entry

    @property
    def balance(self) -> int:
        return self._balance

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def never_negative(self) -> bool:
        return all(entry.balance >= 0 for entry in self._entries)