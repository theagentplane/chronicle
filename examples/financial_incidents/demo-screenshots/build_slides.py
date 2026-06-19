#!/usr/bin/env python3
"""Generate per-slide HTML files for trade demo screenshots."""

from pathlib import Path

DIR = Path(__file__).parent
TEMPLATE_HEAD = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: #0d1117; color: #e6edf3;
    font-family: ui-monospace, Menlo, Monaco, Consolas, monospace; }
  .slide { width: 920px; background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; }
  .hdr { padding: 14px 18px; background: #21262d; border-bottom: 1px solid #30363d; }
  .hdr h2 { margin: 0; font-size: 15px; color: #58a6ff; }
  .body { padding: 18px; }
  pre { margin: 0; padding: 14px; background: #0d1117; border: 1px solid #30363d;
    border-radius: 8px; font-size: 12px; line-height: 1.55; white-space: pre-wrap; }
  .hl { background: rgba(210,153,34,.25); }
  .hl-r { background: rgba(248,81,73,.25); }
  .hl-g { background: rgba(63,185,80,.25); }
  .hl-b { background: rgba(88,166,255,.25); }
  .ann { margin-top: 12px; padding: 10px 12px; border-left: 3px solid #d29922;
    background: rgba(210,153,34,.08); font-size: 12.5px; }
  .ann strong { color: #d29922; }
  .ann.g { border-color: #3fb950; background: rgba(63,185,80,.08); }
  .ann.g strong { color: #3fb950; }
  .ann.r { border-color: #f85149; background: rgba(248,81,73,.08); }
  .ann.r strong { color: #f85149; }
  .ann.b { border-color: #58a6ff; background: rgba(88,166,255,.08); }
  .ann.b strong { color: #58a6ff; }
  .bad { color: #f85149; } .ok { color: #3fb950; } .warn { color: #d29922; }
  .flow { margin: 10px 0; font-size: 12px; }
  .flow span { padding: 4px 8px; border: 1px solid #30363d; border-radius: 5px; margin-right: 6px; }
</style></head><body><div class="slide"><div class="hdr"><h2>{title}</h2></div><div class="body">{body}</div></div></body></html>"""

slides = [
    ("01-scenario-setup", "trade_notional.py — scenario setup", """
<pre>USER_MESSAGE = "Sell about $1,000 of AAPL from my portfolio to rebalance."

INTENDED_NOTIONAL_CENTS = 100_000   <span class="hl"># $1,000 — what user meant</span>
<span class="hl-r">BAD_QUANTITY = 1000</span>                 <span class="hl-r"># shares — agent mistake</span>
SHARE_PRICE_CENTS = 19_000          # $190 / share  → 1000 shares = $190k
<span class="hl-g">MAX_ORDER_NOTIONAL_CENTS = 500_000</span>  <span class="hl-g"># $5,000 — gated fix</span></pre>
<div class="ann r"><strong>① Incident:</strong> User wants ~$1k of AAPL. Agent will send quantity=1000 (shares).</div>
<div class="ann g"><strong>② Fix:</strong> Tool refuses orders above $5,000 notional.</div>
"""),
    ("02-agent-bug", "trade_notional.py — agent bug (@boundary agent@1)", """
<pre><span class="hl-b">@boundary("agent", kind="llm")</span>
def agent_plan(state):
    tool_call = ToolCall(
        name="place_order",
        arguments={<span class="hl-r">"quantity": BAD_QUANTITY</span>},  <span class="hl-r"># 1000 shares ≠ $1,000</span>
    )
    return {..., "tool_calls": [tool_call]}</pre>
<div class="ann b"><strong>Chronicle records</strong> this step as agent@1 envelope.</div>
<div class="ann r"><strong>Bug frozen in fixture</strong> — stubbed unchanged during test.</div>
"""),
    ("03-max-amount-gate", "trade_notional.py — max-amount gate (@boundary place_order@1)", """
<pre><span class="hl-b">@boundary("place_order", kind="tool")</span>
def place_order(symbol, quantity, *, side="sell"):
    notional = quantity * SHARE_PRICE_CENTS
    <span class="hl-g">if _mode == "gated" and notional > MAX_ORDER_NOTIONAL_CENTS:</span>
        return {"status": "blocked", "blocked": True, ...}

    return {"status": "filled", ...}  <span class="hl-r"># ungated: $190k executes</span></pre>
<div class="ann g"><strong>★ Cut-point:</strong> Only this boundary runs live with the fix.</div>
"""),
    ("04-chronicle-test", "run.py — Chronicle cut-point test", """
<div class="flow">
  <span class="warn">agent@1 STUB</span> →
  <span class="ok">place_order@1 LIVE ★</span> →
  <span class="warn">agent@2 LIVE</span>
</div>
<pre>scenario.set_mode(<span class="hl-g">"gated"</span>)
session.load_trace("fixtures/traces/trade-notional/")
session.enable_replay(
    ReplayPlan().stub("agent", 1).live("place_order", 1).live("agent", 2)
)</pre>
<div class="ann b"><strong>No LLM calls.</strong> Agent plan from fixture; tool runs gated code.</div>
"""),
    ("05-record-terminal", "Terminal — python run.py trade record", """
<pre>$ python examples/financial_incidents/run.py trade record

  RECORD  trade-notional
  agent@1       llm  LIVE  → place_order(quantity=<span class="bad">1000</span>)
  place_order@1 tool LIVE  <span class="bad">filled: $190,000.00 total</span>
  agent@2       llm  LIVE  Done. Sold 1000 AAPL...

  Trace exported → fixtures/traces/trade-notional/</pre>
<div class="ann r"><strong>Incident captured</strong> as committed regression fixture.</div>
"""),
    ("06-test-terminal", "Terminal — python run.py trade test", """
<pre>$ python examples/financial_incidents/run.py trade test

  TEST  trade-notional  (cut-point)
  agent@1       llm  <span class="warn">STUB</span>  → place_order(quantity=1000)
  place_order@1 tool <span class="warn">LIVE</span>  <span class="ok">blocked: exceeds maximum $5,000.00</span>
  agent@2       llm  LIVE   Order blocked — $190,000.00...

  <span class="ok">[PASS]</span> order blocked  <span class="ok">[PASS]</span> no shares sold
  <span class="ok">[PASS]</span> agent@1 stubbed  <span class="ok">[PASS]</span> place_order ran live</pre>
<div class="ann g"><strong>Fix verified</strong> — same agent plan, gated tool blocks $190k.</div>
"""),
]

for name, title, body in slides:
    html = TEMPLATE_HEAD.replace("{title}", title).replace("{body}", body)
    (DIR / f"{name}.html").write_text(html)
print(f"Wrote {len(slides)} slides to {DIR}")
