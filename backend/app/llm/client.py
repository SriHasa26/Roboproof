"""LLM client for Nebius Token Factory (OpenAI-compatible).

Every structured call is validated with Pydantic. On a validation failure we retry once,
feeding the validation error back to the model, then raise LLMValidationError.
Transport errors get one retry as well. Calls are logged (latency, tokens, model, outcome)
without secrets or prompt bodies.

PENDING_KEY: nothing here has been run against the real API yet (see docs/NEBIUS_NOTES.md).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
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

    def _log(self, rec: CallRecord) -> None:
        self.records.append(rec)
        if self.sink:
            self.sink(rec)

    def _chat(self, purpose: str, kind: ModelKind, model: str, messages: list[dict], attempt: int, **kw) -> str:
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(model=model, messages=messages, **kw)
        except Exception as e:  # network, auth, rate limit...
            self._log(CallRecord(purpose, kind, model, attempt, time.perf_counter() - t0, None, None, False, type(e).__name__))
            raise LLMTransportError(f"{type(e).__name__}: {e}") from e
        usage = getattr(resp, "usage", None)
        content = resp.choices[0].message.content
        self._log(
            CallRecord(
                purpose, kind, model, attempt, time.perf_counter() - t0,
                getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None), True,
            )
        )
        return content or ""

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
        self, purpose: str, kind: ModelKind, system: str, user: str, schema: type[T], **kw
    ) -> T:
        """Call the model and return a validated `schema` instance, or raise LLMValidationError."""
        _, model = self.settings.require_llm(kind)
        schema_json = json.dumps(schema.model_json_schema())
        sys_full = f"{system}\n\nReply with a single JSON object matching this JSON Schema, and nothing else:\n{schema_json}"
        msgs = [{"role": "system", "content": sys_full}, {"role": "user", "content": user}]
        if self.settings.use_json_schema:  # UNCONFIRMED for Nemotron; off by default
            kw = {**kw, "response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}}
        last_err: str | None = None
        for attempt in (1, 2):
            text = self._chat_with_transport_retry(purpose, kind, model, msgs, attempt, **kw)
            try:
                return schema.model_validate(extract_json(text))
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
