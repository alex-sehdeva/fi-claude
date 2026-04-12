"""Layer 4 — Market data ACTIONS.

This is the only layer that performs I/O.
Functions here fetch, parse, and snapshot market data
into immutable MarketData objects that flow into pricers.

Grokking Simplicity: these are ACTIONS — they depend on *when* they run.
Keep this layer as thin as possible.
"""
