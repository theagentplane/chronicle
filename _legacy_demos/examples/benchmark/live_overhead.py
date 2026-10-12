#!/usr/bin/env python3
"""Recording overhead against real model calls (local Ollama model or Gemini).

Times real model calls through an ``llm`` @boundary with Chronicle recording on
versus off. The two arms are interleaved in one process with one shared client
(order shuffled per pair, fixed seed), so latency drift hits both arms equally.
"Off" calls the raw function via ``__wrapped__`` (zero instrumentation), the same
baseline the incident harness uses. Reports mean, std, and median per arm, and the
difference of means with a 95% confidence interval.

Providers:

- ``ollama`` (default): a model served locally by Ollama (https://ollama.com).
  Needs the Ollama server running and the model pulled (``ollama pull qwen3.5:4b``).
  Uses Ollama's HTTP API directly, so no extra Python dependency.
- ``gemini``: needs ``pip install google-genai`` and GEMINI_API_KEY set in the
  environment (never pass the key on the command line).

Run:

    python -m examples.benchmark.live_overhead --n 50
    python -m examples.benchmark.live_overhead --n 50 --json docs/live-overhead.json
    python -m examples.benchmark.live_overhead --provider gemini --n 50
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import statistics
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from chronicle.boundary import boundary
from chronicle.session import reset_session

PROMPT = "Reply with one short sentence: what is 2 + 2?"
DEFAULT_MODEL = {"ollama": "qwen3.5:4b", "gemini": "gemini-3.6-flash"}


def _summary(samples_ms: list[float]) -> dict[str, float]:
    return {
        "n": len(samples_ms),
        "mean_ms": statistics.mean(samples_ms),
        "std_ms": statistics.stdev(samples_ms),
        "median_ms": statistics.median(samples_ms),
    }


def _ollama_generate(
    host: str, model: str, max_tokens: int, think: bool
) -> Callable[[str], str]:
    """One non-streaming completion from a local Ollama server over plain HTTP."""

    def generate(prompt: str) -> str:
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            # Thinking off by default: a short direct answer keeps call length steady.
            "think": think,
            "options": {"num_predict": max_tokens},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{host}/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read()).get("response", "")

    return generate


def _gemini_generate(model: str, max_tokens: int, thinking_budget: int) -> Callable[[str], str]:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise SystemExit("Set GEMINI_API_KEY in the environment first (see module docstring).")

    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY; shared by both arms
    config_kwargs: dict[str, Any] = {
        "max_output_tokens": max_tokens,
        # No tools are passed; disabling AFC just silences the SDK's startup warning.
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if thinking_budget >= 0:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    config = types.GenerateContentConfig(**config_kwargs)

    def generate(prompt: str) -> str:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        return response.text or ""

    return generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Chronicle recording overhead on real model calls")
    parser.add_argument("--provider", choices=sorted(DEFAULT_MODEL), default="ollama")
    parser.add_argument("--model",
                        help="default: qwen3.5:4b (ollama), gemini-3.6-flash (gemini)")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--think", action="store_true",
                        help="ollama only: let a reasoning model think before answering")
    parser.add_argument("--n", type=int, default=50, help="timed calls per arm")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--thinking-budget", type=int, default=-1,
                        help="gemini only: -1 leaves the model default; 0 disables thinking "
                             "where the model allows it (Gemini 2.5)")
    parser.add_argument("--warmup", type=int, default=3, help="untimed calls first")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between calls")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=Path, help="write summary + raw samples as JSON")
    args = parser.parse_args()

    model = args.model or DEFAULT_MODEL[args.provider]
    if args.provider == "ollama":
        generate = _ollama_generate(args.host, model, args.max_tokens, args.think)
    else:
        generate = _gemini_generate(model, args.max_tokens, args.thinking_budget)

    @boundary("model", kind="llm")
    def call_model(prompt: str) -> dict[str, Any]:
        return {
            "completion": generate(prompt),
            "model": model,
            "finish_reason": "stop",
            "tool_calls": [],
        }

    raw_call = call_model.__wrapped__

    def timed(arm: str) -> float:
        """One timed call. Retries transient provider errors without keeping them."""
        for attempt in range(6):
            try:
                if arm == "on":
                    session = reset_session()
                    session.store = None  # in-memory recording, as in the harness
                    session.begin_trace()
                    start = perf_counter()
                    call_model(PROMPT)
                    elapsed = perf_counter() - start
                    if len(session._recorded_envelopes) != 1:
                        raise RuntimeError("recording arm did not record an envelope")
                else:
                    start = perf_counter()
                    raw_call(PROMPT)
                    elapsed = perf_counter() - start
                return elapsed * 1000.0
            except RuntimeError:
                raise
            except Exception as exc:  # provider errors (rate limits, timeouts)
                code = getattr(exc, "code", "")
                message = str(getattr(exc, "message", "") or exc)[:160]
                print(f"  {arm}: {type(exc).__name__} {code}: {message}")
                if "quota" in message.lower():
                    raise SystemExit("provider quota exhausted; retrying will not help") from exc
                wait = 2.0 ** attempt
                print(f"  retrying in {wait:.0f}s")
                time.sleep(wait)
        raise SystemExit("provider kept failing; try --sleep 6 for a low rate limit")

    for _ in range(args.warmup):  # also loads a local model into memory
        raw_call(PROMPT)

    rng = random.Random(args.seed)
    samples: dict[str, list[float]] = {"on": [], "off": []}
    for i in range(args.n):
        order = ["on", "off"]
        rng.shuffle(order)
        for arm in order:
            samples[arm].append(timed(arm))
            if args.sleep:
                time.sleep(args.sleep)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{args.n} pairs")

    on, off = _summary(samples["on"]), _summary(samples["off"])
    diff = on["mean_ms"] - off["mean_ms"]
    half_width = 1.96 * math.sqrt(on["std_ms"] ** 2 / on["n"] + off["std_ms"] ** 2 / off["n"])

    print(f"\n  model                  : {args.provider}/{model}")
    for arm, s in (("recording on", on), ("recording off", off)):
        print(f"  {arm:<22} : mean {s['mean_ms']:.1f} ms, std {s['std_ms']:.1f} ms, "
              f"median {s['median_ms']:.1f} ms (n={s['n']})")
    print(f"  difference of means    : {diff:+.1f} ms "
          f"(95% CI {diff - half_width:+.1f} to {diff + half_width:+.1f} ms)")
    print()

    if args.json:
        payload = {
            "provider": args.provider,
            "model": model,
            "prompt": PROMPT,
            "max_output_tokens": args.max_tokens,
            "think": args.think,
            "platform": platform.platform(),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "on": on,
            "off": off,
            "diff_mean_ms": diff,
            "diff_ci95_ms": [diff - half_width, diff + half_width],
            "samples_ms": samples,
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  wrote {args.json}")


if __name__ == "__main__":
    main()
