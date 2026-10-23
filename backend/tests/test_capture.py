"""Call-metadata capture: records the API's response ids and metadata, never prompts, replies or keys."""
import json
from types import SimpleNamespace

import pytest

from app.live.capture import STAGE, install, merge_calls


class Fake:
    mode = "ok"

    def create(self, *args, **kwargs):
        if Fake.mode == "boom":
            raise RuntimeError("secret request detail sk-live-123456789012")
        content = "" if Fake.mode == "reasoning" else "hello model reply"
        msg = SimpleNamespace(content=content, reasoning_content="thinking..." if Fake.mode == "reasoning" else None)
        return SimpleNamespace(id="chatcmpl-abc123", model="nvidia/Returned-Model", created=1700000000, system_fingerprint="fp1",
                               choices=[SimpleNamespace(finish_reason="stop", message=msg)], usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3))


def fresh():
    return type("F", (Fake,), {})  # a new class per test: install() wraps a class once


def lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


def test_capture_records_metadata_only(tmp_path):
    Fake.mode = "ok"
    log = tmp_path / "calls.jsonl"
    F = fresh()
    install(str(log), F)
    r = F().create(model="req-model", messages=[{"role": "user", "content": "PROMPT-SECRET-TEXT"}])
    assert r.id == "chatcmpl-abc123"  # the caller still gets the real response
    rec = lines(log)[0]
    assert rec["response_id"] == "chatcmpl-abc123" and rec["response_model"] == "nvidia/Returned-Model" and rec["finish_reason"] == "stop" and rec["reply_channel"] == "content"
    assert rec["request_model"] == "req-model" and rec["prompt_tokens"] == 5 and rec["completion_tokens"] == 3 and rec["latency_s"] >= 0 and rec["started"] < rec["ended"] + "~"
    blob = log.read_text(encoding="utf-8")
    assert "PROMPT-SECRET-TEXT" not in blob and "hello model reply" not in blob  # no prompts, no replies


def test_install_is_idempotent_and_indexes_calls(tmp_path):
    Fake.mode = "ok"
    log = tmp_path / "calls.jsonl"
    F = fresh()
    install(str(log), F)
    install(str(log), F)
    F().create(model="m")
    F().create(model="m")
    assert len(lines(log)) == 2 and lines(log)[1]["index"] == lines(log)[0]["index"] + 1  # wrapped once: one record per call


def test_reasoning_only_channel_and_errors(tmp_path):
    log = tmp_path / "calls.jsonl"
    F = fresh()
    install(str(log), F)
    Fake.mode = "reasoning"
    F().create(model="m")
    assert lines(log)[-1]["reply_channel"] == "reasoning only (content empty)" and lines(log)[-1]["has_reasoning_field"] is True
    Fake.mode = "boom"
    with pytest.raises(RuntimeError):
        F().create(model="m")
    last = lines(log)[-1]
    assert last["error"] == "RuntimeError" and "sk-live" not in log.read_text(encoding="utf-8")  # the exception text is not recorded
    Fake.mode = "ok"


def test_merge_never_invents_fields():
    summary = [{"purpose": "scenario_generation", "model_kind": "fast", "model": "m1", "attempt": 1, "latency_s": 1.0, "prompt_tokens": 10, "completion_tokens": 5, "ok": True, "cached": False},
               {"purpose": "analyst", "model_kind": "reasoning", "model": "m2", "attempt": 1, "latency_s": 2.0, "prompt_tokens": 20, "completion_tokens": 9, "ok": False, "error": "validation: x", "cached": False}]
    old = merge_calls(summary, [])
    assert [c["stage"] for c in old] == [STAGE["scenario_generation"], STAGE["analyst"]]
    assert all(c["response_id"] is None and c["finish_reason"] is None and c["started"] is None and c["model_returned"] is None for c in old)
    assert old[0]["model_requested"] == "m1" and old[1]["retry"] == 1 and old[1]["ok"] is False
    new = merge_calls(summary, [{"index": 1, "response_id": "chatcmpl-1", "response_model": "r1", "finish_reason": "stop", "started": "t0", "ended": "t1", "reply_channel": "content"}])
    assert new[0]["response_id"] == "chatcmpl-1" and new[0]["model_returned"] == "r1" and new[1]["response_id"] is None  # second call has no sidecar record
