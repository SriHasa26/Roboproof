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


SCHEMA += """
CREATE TABLE IF NOT EXISTS batches (
  batch_id TEXT PRIMARY KEY, label TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, policy_json TEXT,
  runner TEXT, scenario_source TEXT, shards_total INTEGER, shards_ok INTEGER, complete INTEGER,
  wall_clock_s REAL, cpu_count INTEGER, n_missing INTEGER
);
CREATE TABLE IF NOT EXISTS scenario_results (
  batch_id TEXT, scenario_id TEXT, seed INTEGER, tag TEXT,
  mass_kg REAL, friction REAL, size_m REAL, pos_offset_x REAL, pos_offset_y REAL, sensor_noise_m REAL,
  gripper_delay_steps INTEGER,
  success INTEGER, collision INTEGER, completion_time_s REAL, final_place_error_m REAL, max_slip_m REAL,
  failure_reason TEXT, PRIMARY KEY (batch_id, scenario_id)
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

    def save_batch(self, batch_id: str, label: str, policy, scenarios, run, scenario_source: str) -> None:
        """Persist one runner batch: the batch row plus one row per scenario that actually ran (missing ones are not stored)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO batches (batch_id,label,policy_json,runner,scenario_source,shards_total,shards_ok,"
            "complete,wall_clock_s,cpu_count,n_missing) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, label, policy.model_dump_json(), run.runner_name, scenario_source, run.shards_total,
             run.shards_ok, int(run.complete), run.wall_clock_s, run.cpu_count, len(run.missing_scenario_ids)),
        )
        by_id = {s.id: s for s in scenarios}
        rows = []
        for r in run.results:
            s = by_id[r.scenario_id]
            rows.append((batch_id, s.id, s.seed, s.tag, s.mass_kg, s.friction, s.size_m, s.pos_offset_x, s.pos_offset_y,
                         s.sensor_noise_m, s.gripper_delay_steps, int(r.success), int(r.collision), r.completion_time_s,
                         r.final_place_error_m, r.max_slip_m, r.failure_reason.value if r.failure_reason else None))
        self.conn.executemany("INSERT OR REPLACE INTO scenario_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def batch_rows(self, batch_id: str) -> list[tuple]:
        return self.conn.execute("SELECT * FROM scenario_results WHERE batch_id=? ORDER BY seed", (batch_id,)).fetchall()

    def llm_calls(self) -> list[tuple]:
        return self.conn.execute("SELECT purpose, model, attempt, ok, prompt_tokens, completion_tokens FROM llm_calls").fetchall()
