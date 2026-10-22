"""Follow-up probe (fast model only, ~7 small real calls).

Part A (1 call): where does the reply go when reasoning_effort="none"? Prints which message fields are non-empty (lengths only).
Part B (5 calls): with extra_body chat_template_kwargs {"enable_thinking": false}, run the REAL generator call path
(complete_json: schema validation + one retry that feeds the error back) and record first-try validity, validity after the retry,
completion tokens and latency. Writes docs/reasoning_control_probe2.json. The key is never printed.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import load_settings  # noqa: E402
from app.llm.client import LLMClient, LLMError  # noqa: E402
from app.scenarios.generator import build_prompt  # noqa: E402
from app.scenarios.proposal import ScenarioProposal  # noqa: E402

NO_THINK = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def main():
    skip_a = "--skip-a" in sys.argv
    outname = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "reasoning_control_probe2.json"
    s = load_settings(dotenv_path=ROOT / ".env")
    system, user = build_prompt()
    out = {"A_reasoning_effort_none_fields": None, "B_enable_thinking_false": []}

    m = None  # part A (reasoning_effort=none) was answered by docs/reasoning_control_probe2.json; not repeated

    for i in range(5):
        c = LLMClient(s)
        t0 = time.perf_counter()
        try:
            prop = c.complete_json("probe_gen", "fast", system, user, ScenarioProposal, max_tokens=4000, **NO_THINK)
            err, ok_final = None, True
        except LLMError as e:
            prop, err, ok_final = None, c.mask(str(e))[:240], False
        recs = c.records
        row = {"i": i, "final_valid": ok_final, "first_try_valid": bool(recs and recs[0].ok), "attempts": len(recs),
               "completion_tokens": [x.completion_tokens for x in recs], "latency_s": round(time.perf_counter() - t0, 2),
               "first_error": next((x.error for x in recs if not x.ok), None), "final_error": err,
               "regions": [(rg.name, sorted(rg.ranges)) for rg in prop.regions] if prop else None}
        out["B_enable_thinking_false"].append(row)
        print("B", json.dumps(row)[:600], flush=True)
    (ROOT / "docs" / outname).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
