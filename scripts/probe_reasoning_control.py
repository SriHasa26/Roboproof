"""One-off probe (fast model only, 3 tiny real calls): can hidden reasoning be capped or disabled on Token Factory?

Variants, each run ONCE with the real scenario-generator prompt and schema:
  baseline            no control (max_tokens=4000 so a runaway cannot get expensive)
  reasoning_effort    top-level `reasoning_effort="none"` (documented in the Nebius API reference; effect on Nemotron UNCONFIRMED)
  enable_thinking     extra_body chat_template_kwargs {"enable_thinking": false} (documented by NVIDIA for Nemotron 3; Nebius pass-through UNCONFIRMED)
Prints tokens, latency and whether the output validates. Never prints the key. Writes docs/reasoning_control_probe.json.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.llm.client import LLMClient, LLMError, extract_json  # noqa: E402
from app.scenarios.generator import build_prompt  # noqa: E402
from app.scenarios.proposal import ScenarioProposal  # noqa: E402

VARIANTS = {
    "baseline": {},
    "reasoning_effort_none": {"reasoning_effort": "none"},
    "enable_thinking_false": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
}


def main():
    s = load_settings(dotenv_path=ROOT / ".env")
    if not (s.api_key and s.model_fast):
        sys.exit("missing key or fast model id")
    system, user = build_prompt()
    out = {}
    for name, extra in VARIANTS.items():
        c = LLMClient(s)
        t0 = time.perf_counter()
        try:
            text = c.complete_text("probe", "fast", system + "\nReply with JSON only matching ScenarioProposal {regions:[{name,rationale,ranges}]}.", user,
                                   max_tokens=4000, **extra)
            err = None
        except LLMError as e:
            text, err = "", c.mask(str(e))[:300]
        rec = c.records[-1] if c.records else None
        valid = None
        if text:
            try:
                ScenarioProposal.model_validate(extract_json(text))
                valid = True
            except Exception as e:
                valid = f"no: {type(e).__name__}: {str(e)[:150]}"
        out[name] = {"error": err, "latency_s": round(time.perf_counter() - t0, 2),
                     "prompt_tokens": rec.prompt_tokens if rec else None, "completion_tokens": rec.completion_tokens if rec else None,
                     "reply_chars": len(text), "validates": valid, "has_think_tags": "<think>" in text}
        print(name, json.dumps(out[name]))
    (ROOT / "docs" / "reasoning_control_probe.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
