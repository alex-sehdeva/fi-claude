"""Layer 2 — Pricers: pure CALCULATIONS.

Every pricer is a pure function: (Instrument, MarketData) → PricingResult.
No I/O, no mutation, no side effects. Deterministic and testable.

Grokking Simplicity: these are CALCULATIONS — same inputs, same outputs, always.
"""
