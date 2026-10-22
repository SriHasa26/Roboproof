"""Real-API smoke test: one call to the fast model and one to the reasoning model, then (with --schema-test) one tiny
`response_format=json_schema` probe per model. Prints the real response text, latency and token usage. The API key is
never printed. A failing call prints the (masked) error and a likely cause, then stops.

Usage: python scripts/smoke_llm.py [--schema-test]
Costs a few thousand tokens in total. Not run in CI.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import BaseModel  # noqa: E402

from app.core.config import ConfigError, load_settings  # noqa: E402
from app.llm.client import LLMClient, LLMError  # noqa: E402

LIKELY = {
    "401": "bad or missing API key", "402": "payment required / credits not applied yet (negative balance?)",
    "404": "model id not found for this key (re-run scripts/list_models.py)", "429": "rate limited, retry later",
}


class Tiny(BaseModel):
    answer: int
    unit: str


def explain(msg: str) -> str:
    for code, cause in LIKELY.items():
        if code in msg:
            return f"likely cause: {cause}"
    return "cause unknown; see the error text"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema-test", action="store_true")
    args = ap.parse_args()
    s = load_settings(dotenv_path=ROOT / ".env")
    for name, v in (("NEBIUS_API_KEY", s.api_key), ("NEBIUS_MODEL_FAST", s.model_fast), ("NEBIUS_MODEL_REASONING", s.model_reasoning)):
        print(f"{name}: {'set' if v else 'MISSING'}")
    if not (s.api_key and s.model_fast and s.model_reasoning):
        return 2
    client = LLMClient(s)
    prompt = ("In one short sentence, say what a robot gripper's friction coefficient does when lifting a heavy object. "
              "Then end with the word DONE.")
    for kind in ("fast", "reasoning"):
        model = s.model_fast if kind == "fast" else s.model_reasoning
        print(f"\n=== {kind}: {model}")
        try:
            text = client.complete_text("smoke", kind, "You are concise.", prompt, max_tokens=600)
        except LLMError as e:
            print("CALL FAILED:", client.mask(str(e)), "|", explain(str(e)))
            return 1
        r = client.records[-1]
        print(f"latency {r.latency_s:.2f}s  prompt_tokens={r.prompt_tokens} completion_tokens={r.completion_tokens}")
        print("response:", text.strip()[:700])
    if args.schema_test:
        for kind in ("fast", "reasoning"):
            model = s.model_fast if kind == "fast" else s.model_reasoning
            print(f"\n=== json_schema probe: {kind}: {model}")
            rf = {"type": "json_schema", "json_schema": {"name": "Tiny", "schema": Tiny.model_json_schema()}}
            try:
                text = client.complete_text("schema_probe", kind, "Reply with JSON only.",
                                            "What is 6 times 7? unit is 'count'.", max_tokens=600, response_format=rf)
            except LLMError as e:
                print("json_schema NOT accepted (request error):", client.mask(str(e))[:400])
                continue
            r = client.records[-1]
            try:
                obj = Tiny.model_validate_json(text.strip())
                print(f"json_schema accepted AND output is exactly valid JSON matching the schema: {obj}  ({r.latency_s:.2f}s)")
            except Exception as e:
                print(f"json_schema accepted by the API but output did not validate strictly ({type(e).__name__}); raw: {text.strip()[:300]!r}")
    u = client.usage_summary()
    print(f"\nTOTAL real calls={u['calls_real']} prompt_tokens={u['prompt_tokens']} completion_tokens={u['completion_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
