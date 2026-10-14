"""Hooks: callbacks that run around a crossing (design section 4.4)."""

from chronicle.framework.hooks.hook_registry import HookRegistry, default_hooks
from chronicle.framework.hooks.hook_types import AbortCall, CallInfo, FunctionHook, Hook

__all__ = ["AbortCall", "CallInfo", "FunctionHook", "Hook", "HookRegistry", "default_hooks"]
