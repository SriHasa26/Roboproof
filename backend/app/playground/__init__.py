"""Playground: run the frozen simulator on user-chosen scenario conditions and policy parameters.

Exploration only, never a gate verdict. The simulator models one task (a gripper picks a cube and places it in a target zone); the
parameter ranges are the frozen ones. No LLM is called except by the optional, guarded analyze endpoint. Playground seeds are always
below 800000, so held-out seeds (>= 900000) and the rehearsal block (800000 to 899999) are never touched.
"""
