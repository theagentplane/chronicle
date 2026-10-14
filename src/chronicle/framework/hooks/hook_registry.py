"""``HookRegistry``: ordered hooks on a session, plus process-wide defaults (design section 4.4).

Hooks run in registration order. Hooks are registered on a session, or as defaults that every
new session inherits; this replaces patching ``reset_session`` to re-attach callbacks.
"""

from collections.abc import Iterator

from chronicle.framework.hooks.hook_types import Hook


class HookRegistry:
    """An ordered list of hooks."""

    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self._hooks: list[Hook] = list(hooks or [])

    def register(self, hook: Hook) -> Hook:
        """Add ``hook`` at the end of the order and return it."""
        self._hooks.append(hook)
        return hook

    def unregister(self, hook: Hook) -> None:
        """Remove ``hook`` if it is registered."""
        if hook in self._hooks:
            self._hooks.remove(hook)

    def clear(self) -> None:
        """Remove every hook."""
        self._hooks.clear()

    def copy(self) -> "HookRegistry":
        """Return an independent registry with the same hooks in the same order."""
        return HookRegistry(self._hooks)

    def __iter__(self) -> Iterator[Hook]:
        return iter(list(self._hooks))

    def __len__(self) -> int:
        return len(self._hooks)


default_hooks = HookRegistry()
"""Defaults inherited by every new session (for example a governor registers itself here)."""
