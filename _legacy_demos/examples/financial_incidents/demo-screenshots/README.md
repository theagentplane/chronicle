# Trade agent demo — annotated screenshots

Six annotated slides for the Chronicle trade-notional demo.

## View screenshots

Open the PNGs in this folder:

| # | File | What it shows |
|---|------|----------------|
| 1 | `01-scenario-setup.png` | Constants: $1k intent vs 1000 shares vs $5k max gate |
| 2 | `02-agent-bug.png` | `@boundary` agent@1 — the bug (quantity=1000) |
| 3 | `03-max-amount-gate.png` | `@boundary` place_order@1 — the gated fix |
| 4 | `04-chronicle-test.png` | `ReplayPlan`: stub agent → live tool → live agent |
| 5 | `05-record-terminal.png` | `run.py trade record` — $190k incident |
| 6 | `06-test-terminal.png` | `run.py trade test` — blocked + PASS |

## Regenerate

```bash
cd examples/financial_incidents/demo-screenshots
python -m http.server 8877 &
python build_slides.py
python capture.py
```

## Source

- Agent: `../trade_notional.py`
- Runner: `../run.py`
