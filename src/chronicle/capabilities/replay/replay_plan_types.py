"""``ReplayPlan``: which boundary and which invocation is ``STUB`` or ``RUN`` (design 7.2).

A replay plan is a logical object, not an entity. The default is ``STUB`` for everything; a
**cut-point** is a replay where at least one boundary is ``RUN`` and the rest are ``STUB``.
Matching is by boundary name plus call count, not by input (design section 7.4).

    ReplayPlan().run("delete_file", 1).run("agent", 2)
"""

from dataclasses import dataclass, field

from chronicle.framework.boundary_enums import BoundaryMode


@dataclass
class ReplayPlan:
    """Per-boundary modes; build it with ``stub(...)`` and ``run(...)``."""

    default: BoundaryMode = BoundaryMode.STUB
    _overrides: dict[tuple[str, int | None], BoundaryMode] = field(default_factory=dict)

    def stub(self, name: str, invocation: int | None = None) -> "ReplayPlan":
        """Return the recording for ``name`` (every call, or just the ``invocation``-th)."""
        self._overrides[(name, invocation)] = BoundaryMode.STUB
        return self

    def run(self, name: str, invocation: int | None = None) -> "ReplayPlan":
        """Execute the real code of ``name`` (every call, or just the ``invocation``-th)."""
        self._overrides[(name, invocation)] = BoundaryMode.RUN
        return self

    def mode_for(self, name: str, invocation_index: int) -> BoundaryMode:
        """The mode of the ``invocation_index``-th call of ``name``; specific beats general."""
        specific = self._overrides.get((name, invocation_index))
        if specific is not None:
            return specific
        general = self._overrides.get((name, None))
        if general is not None:
            return general
        return self.default
