"""Run the hooks of a registry for one event with the failure policy of design section 4.4.

- ``AbortCall`` always propagates.
- Any other ``Exception`` is logged and ignored unless ``fail_call_on_error`` is true, in which
  case it propagates and fails the call.
"""

import logging
from collections.abc import Callable
from typing import Any

from agentplane_primitives.models import Envelope

from chronicle.framework.hooks.hook_registry import HookRegistry
from chronicle.framework.hooks.hook_types import AbortCall, CallInfo

_log = logging.getLogger("chronicle.hooks")


def _guard(method: Callable[..., Any], event: str, fail_call_on_error: bool, *args: Any) -> Any:
    try:
        return method(*args)
    except AbortCall:
        raise
    except Exception:
        if fail_call_on_error:
            raise
        _log.warning("chronicle hook %r failed on %s; continuing", method, event, exc_info=True)
        return None


def run_enter(hooks: HookRegistry, call: CallInfo, fail_call_on_error: bool) -> dict[str, Any]:
    """Run ``enter`` hooks in order and merge the patches; a later patch wins."""
    patch: dict[str, Any] = {}
    for hook in hooks:
        result = _guard(hook.enter, "enter", fail_call_on_error, call)
        if result:
            patch.update(dict(result))
    return patch


def run_leave(hooks: HookRegistry, call: CallInfo, fail_call_on_error: bool) -> None:
    """Run ``leave`` hooks in order."""
    for hook in hooks:
        _guard(hook.leave, "leave", fail_call_on_error, call)


def run_crossing(
    hooks: HookRegistry, call: CallInfo, result: Any, fail_call_on_error: bool
) -> None:
    """Run ``crossing`` hooks in order."""
    for hook in hooks:
        _guard(hook.crossing, "crossing", fail_call_on_error, call, result)


def run_record(hooks: HookRegistry, envelope: Envelope, fail_call_on_error: bool) -> None:
    """Run ``record`` hooks in order."""
    for hook in hooks:
        _guard(hook.record, "record", fail_call_on_error, envelope)
