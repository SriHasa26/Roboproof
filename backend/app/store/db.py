"""SQLite store for runs and LLM call telemetry."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core.schemas import Run
from ..llm.client import CallRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT CURRENT_TIMESTAMP, run_id TEXT,
  purpose TEXT, model_kind TEXT, model TEXT, attempt INTEGER, latency_s REAL,
  prompt_tokens INTEGER, completion_tokens INTEGER, ok INTEGER, error TEXT
);
"""


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def save_run(self, run: Run) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, body) VALUES (?,?,?)",
            (run.id, run.created_at.isoformat(), run.model_dump_json()),
        )
        self.conn.commit()

    def load_run(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def log_llm_call(self, rec: CallRecord, run_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO llm_calls (run_id,purpose,model_kind,model,attempt,latency_s,prompt_tokens,completion_tokens,ok,error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, rec.purpose, rec.model_kind, rec.model, rec.attempt, rec.latency_s,
             rec.prompt_tokens, rec.completion_tokens, int(rec.ok), rec.error),
        )
        self.conn.commit()

    def llm_calls(self) -> list[tuple]:
        return self.conn.execute("SELECT purpose, model, attempt, ok, prompt_tokens, completion_tokens FROM llm_calls").fetchall()
