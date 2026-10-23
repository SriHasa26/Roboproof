"""Record what the API itself returned for every chat call (provider response id, returned model id, finish reason, reply channel, token usage,
UTC timestamps) into a JSONL sidecar. It wraps the OpenAI SDK's create() at runtime from OUTSIDE the frozen pipeline: no frozen file changes.

Never recorded: prompts, replies, API keys, headers. The sidecar holds metadata only. Used by scripts/run_live_pipeline.py for live runs.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

_LOCK = threading.Lock()
_STATE = {"n": 0, "installed": False}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds")


def describe(resp, req_model, started: float, ended: float, n: int) -> dict:
    """Metadata of one chat completion response, tolerant of missing fields."""
    ch = (getattr(resp, "choices", None) or [None])[0]
    msg = getattr(ch, "message", None)
    content = getattr(msg, "content", None) or ""
    reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
    usage = getattr(resp, "usage", None)
    return {
        "index": n, "started": _iso(started), "ended": _iso(ended), "latency_s": round(ended - started, 3),
        "request_model": req_model, "response_model": getattr(resp, "model", None), "response_id": getattr(resp, "id", None),
        "created": getattr(resp, "created", None), "finish_reason": getattr(ch, "finish_reason", None),
        "reply_channel": "content" if content else ("reasoning only (content empty)" if reasoning else "empty"),
        "has_reasoning_field": bool(reasoning), "reply_chars": len(content),
        "prompt_tokens": getattr(usage, "prompt_tokens", None), "completion_tokens": getattr(usage, "completion_tokens", None),
        "system_fingerprint": getattr(resp, "system_fingerprint", None),
    }


def _append(path: str, rec: dict) -> None:
    with _LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def install(log_path: str, completions_cls=None) -> None:
    """Wrap Completions.create once. `completions_cls` lets tests inject a stand-in class."""
    if completions_cls is None:
        from openai.resources.chat.completions import Completions as completions_cls  # type: ignore[assignment]
    if getattr(completions_cls.create, "_roboproof_capture", False):
        return
    orig = completions_cls.create

    def create(self, *args, **kwargs):
        with _LOCK:
            _STATE["n"] += 1
            n = _STATE["n"]
        t0 = time.time()
        try:
            resp = orig(self, *args, **kwargs)
        except Exception as e:  # keep the failure visible; never the message text (it could echo request details)
            _append(log_path, {"index": n, "started": _iso(t0), "ended": _iso(time.time()), "latency_s": round(time.time() - t0, 3), "request_model": kwargs.get("model"),
                               "error": type(e).__name__})
            raise
        try:
            _append(log_path, describe(resp, kwargs.get("model"), t0, time.time(), n))
        except Exception:
            pass  # metadata capture must never break a run
        return resp

    create._roboproof_capture = True  # type: ignore[attr-defined]
    completions_cls.create = create  # type: ignore[method-assign]


def merge_calls(summary_calls: list[dict], sidecar: list[dict]) -> list[dict]:
    """Join the pipeline's own call records (summary.json) with the sidecar by order. Fields the pipeline did not record stay None
    (the UI shows 'not recorded'); nothing is invented."""
    out = []
    for i, c in enumerate(summary_calls):
        side = sidecar[i] if i < len(sidecar) else {}
        out.append({
            "n": i + 1, "stage": STAGE.get(c.get("purpose"), c.get("purpose")), "purpose": c.get("purpose"), "role": c.get("model_kind"),
            "model_requested": c.get("model"), "model_returned": side.get("response_model"), "response_id": side.get("response_id"),
            "started": side.get("started"), "ended": side.get("ended"), "latency_s": c.get("latency_s"),
            "prompt_tokens": c.get("prompt_tokens"), "completion_tokens": c.get("completion_tokens"), "finish_reason": side.get("finish_reason"),
            "reply_channel": side.get("reply_channel"), "cached": c.get("cached"), "retry": c.get("attempt"), "ok": c.get("ok"), "error": c.get("error"),
        })
    return out


STAGE = {"scenario_generation": "Generate", "analyst": "Analyze", "fixer": "Fix", "interpret": "Interpret"}
