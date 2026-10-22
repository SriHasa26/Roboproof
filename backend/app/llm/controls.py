"""Per-stage LLM request controls. Part of the frozen pipeline. Evidence and measurements: docs/NEBIUS_NOTES.md section 8.

Generator (fast model, Nemotron Nano): hidden reasoning is turned OFF with the chat-template switch enable_thinking=false, passed
through Token Factory as extra_body.chat_template_kwargs (documented by NVIDIA for Nemotron 3; confirmed by run on Token Factory,
2026-10-22). The Nebius-documented `reasoning_effort="none"` was tried and does NOT work on this model (the whole reply landed in a
`reasoning` field and `content` was empty). With reasoning on and an EARLIER version of the prompt (docs/reasoning_control_probe.json) the model spent the whole 4,000-token
cap without producing visible output. The output JSON is about 300 to 550 tokens, so the cap is generous.

Analyst and fixer (reasoning model, Nemotron Ultra): reasoning stays ON; the caps only stop a runaway call. Measured usage in
rehearsal_001 was 4,660 (analyst) and 1,261 / 1,916 (fixer) completion tokens including hidden reasoning.
"""
GENERATOR_MAX_TOKENS = 1500
GENERATOR_EXTRA: dict = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
ANALYST_MAX_TOKENS = 10000
FIXER_MAX_TOKENS = 6000
