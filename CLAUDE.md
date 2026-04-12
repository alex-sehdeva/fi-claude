# fi-claude

Legible, functional fixed-income pricers.

## Design Philosophy

**Grokking Simplicity (Eric Normand)** — every module is classified:

- **DATA** (Layer 0): Frozen Pydantic models in `src/fi_claude/data/`. No methods that do I/O.
- **CALCULATIONS** (Layers 1-3): Pure functions in `curves/`, `pricers/`, `risk/`. Same inputs → same outputs.
- **ACTIONS** (Layer 4): I/O in `market/`. Thin as possible. Produces immutable MarketData snapshots.

Every pricer is a pure function: `(Instrument, MarketData) → PricingResult`.

## Architecture Decision: Build, Don't Wrap

We build from first principles rather than wrapping Strata or QuantLib because:
1. **Legibility** is priority #1 — both libraries impose patterns (Observer/Observable, Joda-Beans) that leak through wrappers
2. TBAs require greenfield regardless
3. BRL Pre-CDI needs custom work on either platform
4. QuantLib-Python is an **optional utility dependency** for math (interpolation, calibration), not an architectural foundation

## Instruments

| Instrument | Module | Status |
|---|---|---|
| BRL Pre-CDI Swap | `pricers/brl_pre_cdi.py` | Foundation |
| Inflation-Linked Bond | `pricers/inflation_bond.py` | Foundation |
| Cross-Currency Basis Swap | `pricers/xccy_basis_swap.py` | Foundation |
| TBA | `pricers/tba.py` | Foundation |

## Stack

- Python 3.12+, uv, pytest, Pydantic v2
- Optional: QuantLib-Python (for curve calibration math)
- Immutable data, pure functions, stratified layers

## Commands

```bash
uv sync --all-extras     # install everything
uv run pytest             # run tests
uv run mypy src/          # type check
uv run ruff check src/    # lint
```

## Rules

- Never mix ACTIONS into CALCULATIONS — if a function does I/O, it belongs in `market/`
- All data models must be `frozen=True`
- Pricers take `(Instrument, MarketData) → PricingResult` — no hidden state
- Tests need no mocks — pure functions are trivially testable
