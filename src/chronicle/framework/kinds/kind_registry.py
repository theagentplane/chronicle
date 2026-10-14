"""The kind registry: one strategy per ``Kind`` member (design section 4.2).

``kind`` is a closed enum from primitives, so there are no unregistered kinds. Declaring a
boundary with any other kind fails at declaration time (``parse_kind``).
"""

from agentplane_primitives.enums import Kind

from chronicle.framework.kinds.kind_strategy_types import KindStrategy
from chronicle.framework.kinds.llm_strategy import LlmStrategy
from chronicle.framework.kinds.tool_strategy import ToolStrategy

_STRATEGIES: dict[Kind, KindStrategy] = {
    Kind.LLM: LlmStrategy(),
    Kind.TOOL: ToolStrategy(),
}

_RETIRED = {"router", "custom"}


def strategy_for(kind: Kind) -> KindStrategy:
    """Return the strategy for ``kind``."""
    return _STRATEGIES[kind]


def parse_kind(value: str | Kind) -> Kind:
    """Return the ``Kind`` for ``value`` or raise ``ValueError`` at declaration time."""
    try:
        kind = Kind(value)
    except ValueError:
        hint = (
            " ('router' and 'custom' were retired: use 'tool', or 'llm' for a model call)"
            if str(value) in _RETIRED
            else ""
        )
        allowed = ", ".join(repr(k.value) for k in Kind)
        raise ValueError(
            f"unknown boundary kind {value!r}; expected one of {allowed}{hint}"
        ) from None
    if kind not in _STRATEGIES:  # a kind added to primitives before its strategy exists here
        raise ValueError(f"no strategy registered for kind {kind.value!r}")
    return kind
