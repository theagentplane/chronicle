"""Build the canonical sampling parameters from the arguments a caller passed (design 2.3)."""

from agentplane_primitives.models import LlmParams
from pydantic import JsonValue

_MAX_TOKENS_KEYS = ("max_tokens", "max_completion_tokens", "max_output_tokens")
_STOP_KEYS = ("stop", "stop_sequences")


def params_from_arguments(raw: dict[str, JsonValue]) -> LlmParams:
    """Read the sampling settings (temperature, top_p, max_tokens, seed, stop) the caller set."""
    temperature = raw.get("temperature")
    top_p = raw.get("top_p")
    seed = raw.get("seed")
    max_tokens = next((raw[key] for key in _MAX_TOKENS_KEYS if isinstance(raw.get(key), int)), None)
    stop: list[str] | None = None
    for key in _STOP_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            stop = [value]
        elif isinstance(value, list):
            stop = [item for item in value if isinstance(item, str)]
        if stop is not None:
            break
    return LlmParams(
        temperature=float(temperature) if _is_number(temperature) else None,  # type: ignore[arg-type]
        top_p=float(top_p) if _is_number(top_p) else None,  # type: ignore[arg-type]
        max_tokens=max_tokens if isinstance(max_tokens, int) and max_tokens >= 0 else None,
        seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        stop=stop,
    )


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
