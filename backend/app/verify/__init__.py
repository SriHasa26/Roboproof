"""Verification of recorded official runs: recompute what can be recomputed, re-simulate what may be re-simulated, and say exactly what cannot.

Pure code, no LLM calls. It imports the gate's own helpers (read-only) so thresholds and the verdict precedence are the real ones.
Held-out seeds (900000 and up) are never simulated here: only the gate may use them. Held-out counts are checked for internal
consistency (Wilson intervals, thresholds, verdict), not re-simulated.
"""
