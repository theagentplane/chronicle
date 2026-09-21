"""Replay plan: stub vs live per boundary invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BoundaryMode(str, Enum):
    STUB = "stub"
    LIVE = "live"


@dataclass
class ReplayPlan:
    """
    Controls which annotated boundaries stub from fixtures vs run live code.

    Default for replay: stub everything. Opt in to live with live().
    """

    default: BoundaryMode = BoundaryMode.STUB
    _overrides: dict[tuple[str, int | None], BoundaryMode] = field(default_factory=dict)

    def stub(self, name: str, invocation: int | None = None) -> ReplayPlan:
        self._overrides[(name, invocation)] = BoundaryMode.STUB
        if invocation is None:
            self._overrides[(name, None)] = BoundaryMode.STUB
        return self

    def live(self, name: str, invocation: int | None = None) -> ReplayPlan:
        self._overrides[(name, invocation)] = BoundaryMode.LIVE
        if invocation is None:
            self._overrides[(name, None)] = BoundaryMode.LIVE
        return self

    def stub_all(self) -> ReplayPlan:
        self.default = BoundaryMode.STUB
        return self

    def mode_for(self, name: str, invocation_index: int) -> BoundaryMode:
        specific = self._overrides.get((name, invocation_index))
        if specific is not None:
            return specific
        general = self._overrides.get((name, None))
        if general is not None:
            return general
        return self.default

    def should_stub(self, name: str, invocation_index: int) -> bool:
        return self.mode_for(name, invocation_index) == BoundaryMode.STUB
