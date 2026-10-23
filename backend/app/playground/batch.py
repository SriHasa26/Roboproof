"""CSV / pasted-table batches: parsing with row-level errors, the template, and a spreadsheet-safe results export. No model is involved."""
from __future__ import annotations

import csv
import io
import math

from ..core.bounds import SCENARIO_BOUNDS

MAX_ROWS = 200
MAX_BYTES = 100 * 1024
MAX_ERRORS_SHOWN = 40
BATCH_SEED_BASE = 700_000  # row i gets seed 700000 + i: inside the playground range, never held-out or rehearsal, deterministic by row index
COLUMNS = list(SCENARIO_BOUNDS)
INT_COLUMNS = {"gripper_delay_steps"}


def csv_cell(v):
    """Neutralise spreadsheet formula injection: a TEXT cell starting with = + - or @ (or a tab/CR) gets a leading apostrophe. Numbers stay numbers."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([csv_cell(h) for h in header])
    for r in rows:
        w.writerow([csv_cell(x) for x in r])
    return buf.getvalue()


def template_csv(presets: list[dict]) -> str:
    rows = [[p["scenario"][k] for k in COLUMNS] for p in presets if p.get("scenario")]
    return to_csv(COLUMNS, rows)


class BatchError(Exception):
    def __init__(self, status: int, code: str, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.errors = status, code, message, errors or []


def _err(row: int, line: int, field: str, problem: str) -> dict:
    return {"row": row, "line": line, "field": field, "problem": problem}


def parse_batch(text: str) -> list[dict]:
    """Return one dict of validated scenario fields per data row, or raise BatchError listing every problem (nothing is run if any row is invalid)."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise BatchError(413, "too_large", f"The table is larger than {MAX_BYTES // 1024} KB.")
    text = text.lstrip("﻿")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if not first:
        raise BatchError(422, "empty", "The table is empty. It needs a header row and at least one data row.")
    delim = "\t" if "\t" in first and "," not in first else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header: list[str] | None = None
    rows: list[tuple[int, list[str]]] = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        if header is None:
            header = [c.strip().lower() for c in cells]
        else:
            rows.append((reader.line_num, [c.strip() for c in cells]))
    errs: list[dict] = []
    assert header is not None
    seen: set[str] = set()
    for h in header:
        if h in seen:
            errs.append(_err(0, 1, h, "duplicate column"))
        seen.add(h)
        if h not in SCENARIO_BOUNDS:
            errs.append(_err(0, 1, h, f"unknown column; the columns are exactly: {', '.join(COLUMNS)}"))
    for c in COLUMNS:
        if c not in seen:
            errs.append(_err(0, 1, c, "missing column"))
    if errs:
        raise BatchError(422, "invalid_header", "The header row does not match the scenario columns.", errs[:MAX_ERRORS_SHOWN])
    if not rows:
        raise BatchError(422, "no_rows", "The table has a header but no data rows.")
    if len(rows) > MAX_ROWS:
        raise BatchError(413, "too_many_rows", f"At most {MAX_ROWS} rows are allowed; the table has {len(rows)}.")
    out: list[dict] = []
    for i, (line, cells) in enumerate(rows, 1):
        if len(cells) != len(header):
            errs.append(_err(i, line, "(row)", f"has {len(cells)} cells but the header has {len(header)}"))
            continue
        rec: dict = {}
        for h, raw in zip(header, cells):
            lo, hi = SCENARIO_BOUNDS[h]
            try:
                v = float(raw)
            except ValueError:
                errs.append(_err(i, line, h, f"'{raw[:20]}' is not a number"))
                continue
            if not math.isfinite(v):
                errs.append(_err(i, line, h, "must be a finite number"))
            elif h in INT_COLUMNS and v != int(v):
                errs.append(_err(i, line, h, f"{raw} must be a whole number"))
            elif not (lo <= v <= hi):
                errs.append(_err(i, line, h, f"{raw} is outside the allowed range {lo} to {hi}"))
            else:
                rec[h] = int(v) if h in INT_COLUMNS else v
        out.append(rec)
    if errs:
        n = len(errs)
        raise BatchError(422, "invalid_rows", f"{n} problem{'s' if n != 1 else ''} in the table; nothing was run." + (f" Showing the first {MAX_ERRORS_SHOWN}." if n > MAX_ERRORS_SHOWN else ""), errs[:MAX_ERRORS_SHOWN])
    return out


RESULT_HEADER = COLUMNS + ["seed", "scenario_id", "passed", "failure_reason", "completion_time_s", "collision", "default_passed", "default_failure_reason"]


def results_csv(rows: dict) -> str:
    """Per-row results as spreadsheet-safe CSV (text cells are neutralised against formula injection)."""
    body = []
    for i in range(len(rows["ids"])):
        body.append([rows[c][i] for c in COLUMNS] + [rows["seed"][i], rows["ids"][i], "yes" if rows["ok"][i] else "no", rows["reason"][i] or "", rows["time_s"][i],
                                                     "yes" if rows["collision"][i] else "no", "yes" if rows["default_ok"][i] else "no", rows["default_reason"][i] or ""])
    return to_csv(RESULT_HEADER, body)
