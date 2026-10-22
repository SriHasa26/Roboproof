"""LLM client for Nebius Token Factory (OpenAI-compatible).

Every structured call is validated with Pydantic (and an optional code-side `validator`, used for grounding checks).
On a validation failure we retry once, feeding the error back to the model, then raise LLMValidationError.
Transport errors get one retry as well.

Safety / cost controls:
- The API key is never logged or returned; error text is masked.
- MAX_LLM_CALLS_PER_RUN caps real network calls per client (a run uses one client). Retries count.
- LLM_DEV_CACHE=1 enables an on-disk response cache for development only. Every record carries `cached`; official
  recorded runs must use LLM_DEV_CACHE=0 (the default).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from ..core.config import Settings

T = TypeVar("T", bound=BaseModel)

ModelKind = Literal["fast", "reasoning"]


class LLMError(RuntimeError):
    pass


class LLMTransportError(LLMError):
    pass


class LLMValidationError(LLMError):
    pass


class LLMBudgetExceeded(LLMError):
    pass


@dataclass
class CallRecord:
    purpose: str
    model_kind: str
    model: str
    attempt: int
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    ok: bool
    error: str | None = None
    cached: bool = False


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model reply (strips <think> blocks and code fences)."""
    if text is None:
        raise ValueError("empty model reply")
    text = _THINK.sub("", text).strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # last resort: first balanced {...} or [...] block
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no valid JSON found in model reply")


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token). An ESTIMATE, only for pre-run projections."""
    return max(1, len(text) // 4)


@dataclass
class _Cached:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        openai_client: Any | None = None,
        sink: Callable[[CallRecord], None] | None = None,
    ):
        self.settings = settings
        self._client = openai_client
        self.sink = sink
        self.records: list[CallRecord] = []
        self.real_calls = 0

    # ---- secrets
    def mask(self, text: str) -> str:
        key = self.settings.api_key
        return text.replace(key, "***") if key and key in text else text

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            from ..core.config import ConfigError

            if not self.settings.api_key:
                raise ConfigError("NEBIUS_API_KEY is not set (see .env.example)")
            self._client = OpenAI(
                api_key=self.settings.api_key, base_url=self.settings.base_url, timeout=self.settings.llm_timeout_s, max_retries=0
            )
        return self._client

    # ---- accounting
    def _log(self, rec: CallRecord) -> None:
        self.records.append(rec)
        if self.sink:
            self.sink(rec)

    def usage_summary(self) -> dict:
        real = [r for r in self.records if not r.cached]
        return {
            "calls_total": len(self.records), "calls_real": len(real), "calls_cached": len(self.records) - len(real),
            "prompt_tokens": sum(r.prompt_tokens or 0 for r in real),
            "completion_tokens": sum(r.completion_tokens or 0 for r in real),
            "max_calls": self.settings.max_calls_per_run, "any_cached": any(r.cached for r in self.records),
        }

    # ---- dev cache
    def _cache_path(self, model: str, messages: list[dict], kw: dict) -> Path:
        h = hashlib.sha256(json.dumps({"m": model, "msgs": messages, "kw": kw}, sort_keys=True, default=str).encode()).hexdigest()
        return Path(self.settings.cache_dir) / f"{h}.json"

    def _cache_get(self, path: Path) -> _Cached | None:
        if not self.settings.dev_cache or not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return _Cached(d["content"], d.get("prompt_tokens"), d.get("completion_tokens"))

    def _cache_put(self, path: Path, content: str, pt, ct) -> None:
        if not self.settings.dev_cache:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"content": content, "prompt_tokens": pt, "completion_tokens": ct}), encoding="utf-8")

    # ---- calls
    def _chat(self, purpose: str, kind: ModelKind, model: str, messages: list[dict], attempt: int, **kw) -> str:
        t0 = time.perf_counter()
        path = self._cache_path(model, messages, kw)
        hit = self._cache_get(path)
        if hit is not None:
            self._log(CallRecord(purpose, kind, model, attempt, 0.0, hit.prompt_tokens, hit.completion_tokens, True, cached=True))
            return hit.content
        if self.real_calls >= self.settings.max_calls_per_run:
            raise LLMBudgetExceeded(f"MAX_LLM_CALLS_PER_RUN={self.settings.max_calls_per_run} reached before '{purpose}'")
        self.real_calls += 1
        try:
            resp = self.client.chat.completions.create(model=model, messages=messages, **kw)
        except Exception as e:  # network, auth, rate limit...
            self._log(CallRecord(purpose, kind, model, attempt, time.perf_counter() - t0, None, None, False, type(e).__name__))
            raise LLMTransportError(self.mask(f"{type(e).__name__}: {e}")) from e
        usage = getattr(resp, "usage", None)
        content = resp.choices[0].message.content or ""
        pt, ct = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        self._log(CallRecord(purpose, kind, model, attempt, time.perf_counter() - t0, pt, ct, True))
        self._cache_put(path, content, pt, ct)
        return content

    def _chat_with_transport_retry(self, purpose, kind, model, messages, attempt, **kw) -> str:
        try:
            return self._chat(purpose, kind, model, messages, attempt, **kw)
        except LLMTransportError:
            return self._chat(purpose, kind, model, messages, attempt, **kw)

    def complete_text(self, purpose: str, kind: ModelKind, system: str, user: str, **kw) -> str:
        _, model = self.settings.require_llm(kind)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self._chat_with_transport_retry(purpose, kind, model, msgs, 1, **kw)

    def complete_json(
        self, purpose: str, kind: ModelKind, system: str, user: str, schema: type[T],
        validator: Callable[[T], None] | None = None, **kw
    ) -> T:
        """Call the model and return a validated `schema` instance, or raise LLMValidationError.

        `validator` runs after schema validation and may raise ValueError (for example a grounding check); its message
        is fed back to the model on the single retry.
        """
        _, model = self.settings.require_llm(kind)
        schema_json = json.dumps(schema.model_json_schema())
        sys_full = f"{system}\n\nReply with a single JSON object matching this JSON Schema, and nothing else:\n{schema_json}"
        msgs = [{"role": "system", "content": sys_full}, {"role": "user", "content": user}]
        if self.settings.use_json_schema:  # only after it is confirmed for the chosen model (see docs/NEBIUS_NOTES.md)
            kw = {**kw, "response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}}
        last_err: str | None = None
        for attempt in (1, 2):
            text = self._chat_with_transport_retry(purpose, kind, model, msgs, attempt, **kw)
            try:
                obj = schema.model_validate(extract_json(text))
                if validator is not None:
                    validator(obj)
                return obj
            except (ValueError, ValidationError) as e:
                last_err = str(e)
                self._mark_invalid(last_err)
                msgs = msgs + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"Your reply failed validation:\n{last_err}\nReturn corrected JSON only."},
                ]
        raise LLMValidationError(f"{purpose}: output failed validation after retry: {last_err}")

    def _mark_invalid(self, err: str) -> None:
        if self.records:
            self.records[-1].ok = False
            self.records[-1].error = "validation: " + err[:200]
