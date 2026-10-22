"""Environment-driven configuration. No keys or model IDs are hardcoded."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"  # CONFIRMED-DOCS, see docs/NEBIUS_NOTES.md


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model_fast: str | None
    model_reasoning: str | None
    use_json_schema: bool
    llm_timeout_s: float
    db_path: str
    dev_cache: bool = False
    cache_dir: str = "backend/data/llm_cache"
    max_calls_per_run: int = 12

    def require_llm(self, kind: str) -> tuple[str, str]:
        """Return (api_key, model_id) for 'fast' or 'reasoning', or fail loudly."""
        if kind not in ("fast", "reasoning"):
            raise ConfigError(f"unknown model kind {kind!r}")
        if not self.api_key:
            raise ConfigError("NEBIUS_API_KEY is not set (see .env.example)")
        model = self.model_fast if kind == "fast" else self.model_reasoning
        if not model:
            var = "NEBIUS_MODEL_FAST" if kind == "fast" else "NEBIUS_MODEL_REASONING"
            raise ConfigError(f"{var} is not set; run scripts/list_models.py")
        return self.api_key, model

    def redacted(self) -> dict:
        d = dict(self.__dict__)
        d["api_key"] = "***" if self.api_key else None
        return d


def load_settings(env: dict | None = None, dotenv_path: str | Path | None = None) -> Settings:
    if env is None:
        load_dotenv(dotenv_path, override=False)
        env = os.environ
    return Settings(
        api_key=env.get("NEBIUS_API_KEY") or None,
        base_url=env.get("NEBIUS_BASE_URL") or DEFAULT_BASE_URL,
        model_fast=env.get("NEBIUS_MODEL_FAST") or None,
        model_reasoning=env.get("NEBIUS_MODEL_REASONING") or None,
        use_json_schema=env.get("NEBIUS_USE_JSON_SCHEMA", "0") == "1",
        llm_timeout_s=float(env.get("LLM_TIMEOUT_S", "120")),
        db_path=env.get("ROBOPROOF_DB", "backend/data/roboproof.sqlite"),
        dev_cache=env.get("LLM_DEV_CACHE", "0") == "1",
        cache_dir=env.get("LLM_CACHE_DIR", "backend/data/llm_cache"),
        max_calls_per_run=int(env.get("MAX_LLM_CALLS_PER_RUN", "12")),
    )
