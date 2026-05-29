"""
storage/history.py — SQLite history for all pipeline runs

Stores:
  - runs: id, task, type, status, timestamps, verdict
  - events: linked to run_id, full event data
  - files: workspace file snapshots at completion

Usage:
    db = History("runs.db")
    run_id = db.start_run("Build a todo app", "coding")
    db.add_event(run_id, event)
    db.finish_run(run_id, "PASS", {"architect": "...", "coder": "..."})
    
    runs = db.list_runs(limit=20)
    events = db.get_events(run_id)
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.events import Event


class History:
    def __init__(self, db_path: str | Path = "runs.db"):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ── Connection ────────────────────────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task        TEXT NOT NULL,
                task_type   TEXT DEFAULT 'coding',
                status      TEXT DEFAULT 'running',
                verdict     TEXT DEFAULT '',
                config      TEXT DEFAULT '{}',
                results     TEXT DEFAULT '{}',
                started_at  REAL NOT NULL,
                finished_at REAL,
                duration    REAL
            );

            CREATE TABLE IF NOT EXISTS events (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id  INTEGER NOT NULL,
                agent   TEXT NOT NULL,
                type    TEXT NOT NULL,
                data    TEXT DEFAULT '{}',
                ts      REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS files (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id  INTEGER NOT NULL,
                path    TEXT NOT NULL,
                size    INTEGER DEFAULT 0,
                content TEXT,
                ts      REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_files_run  ON files(run_id);
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
        """)
        self.conn.commit()

    # ── Runs ──────────────────────────────────────────────────────────────────

    def start_run(self, task: str, task_type: str = "coding",
                  config: dict | None = None) -> int:
        """Create a new run. Returns run_id."""
        cur = self.conn.execute(
            "INSERT INTO runs (task, task_type, status, config, started_at) VALUES (?,?,?,?,?)",
            (task, task_type, "running", json.dumps(config or {}), time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, verdict: str, results: dict | None = None) -> None:
        """Mark a run as complete."""
        now = time.time()
        row = self.conn.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        duration = (now - row["started_at"]) if row else 0

        self.conn.execute(
            "UPDATE runs SET status=?, verdict=?, results=?, finished_at=?, duration=? WHERE id=?",
            ("done", verdict, json.dumps(results or {}), now, duration, run_id),
        )
        self.conn.commit()

    def fail_run(self, run_id: int, error: str) -> None:
        """Mark a run as failed."""
        now = time.time()
        row = self.conn.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        duration = (now - row["started_at"]) if row else 0

        self.conn.execute(
            "UPDATE runs SET status=?, verdict=?, results=?, finished_at=?, duration=? WHERE id=?",
            ("failed", "FAIL", json.dumps({"error": error}), now, duration, run_id),
        )
        self.conn.commit()

    def list_runs(self, limit: int = 50, offset: int = 0,
                  status: str | None = None) -> list[dict]:
        """List runs, newest first."""
        query  = "SELECT * FROM runs"
        params: list = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def delete_run(self, run_id: int) -> bool:
        self.conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
        self.conn.commit()
        return True

    # ── Events ────────────────────────────────────────────────────────────────

    def add_event(self, run_id: int, event: Event) -> None:
        """Store an event linked to a run."""
        self.conn.execute(
            "INSERT INTO events (run_id, agent, type, data, ts) VALUES (?,?,?,?,?)",
            (run_id, event.agent, event.type, json.dumps(event.data), event.ts),
        )
        # Commit in batches — don't commit every single event
        # Caller should periodically call flush_events()

    def flush_events(self) -> None:
        """Commit pending events."""
        self.conn.commit()

    def get_events(self, run_id: int, event_type: str | None = None) -> list[dict]:
        """Get all events for a run."""
        query  = "SELECT * FROM events WHERE run_id=?"
        params: list = [run_id]
        if event_type:
            query += " AND type=?"
            params.append(event_type)
        query += " ORDER BY ts ASC"

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_events(self, run_id: int) -> dict:
        """Count events by type for a run."""
        rows = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM events WHERE run_id=? GROUP BY type",
            (run_id,),
        ).fetchall()
        return {r["type"]: r["cnt"] for r in rows}

    # ── Files ─────────────────────────────────────────────────────────────────

    def save_workspace_snapshot(self, run_id: int, workspace: Path) -> int:
        """Snapshot all files in workspace at this moment."""
        count = 0
        if not workspace.exists():
            return 0

        for f in sorted(workspace.rglob("*")):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                content = "(binary file)"

            self.conn.execute(
                "INSERT INTO files (run_id, path, size, content, ts) VALUES (?,?,?,?,?)",
                (run_id, str(f.relative_to(workspace)), f.stat().st_size, content, time.time()),
            )
            count += 1

        self.conn.commit()
        return count

    def get_files(self, run_id: int) -> list[dict]:
        """Get file snapshots for a run."""
        rows = self.conn.execute(
            "SELECT id, run_id, path, size, ts FROM files WHERE run_id=? ORDER BY path",
            (run_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_file_content(self, file_id: int) -> str | None:
        row = self.conn.execute("SELECT content FROM files WHERE id=?", (file_id,)).fetchone()
        return row["content"] if row else None

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Overall statistics."""
        total   = self.conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()["c"]
        done    = self.conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='done'").fetchone()["c"]
        failed  = self.conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='failed'").fetchone()["c"]
        running = self.conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='running'").fetchone()["c"]

        avg_dur = self.conn.execute(
            "SELECT AVG(duration) as d FROM runs WHERE duration IS NOT NULL"
        ).fetchone()["d"] or 0

        pass_cnt = self.conn.execute(
            "SELECT COUNT(*) as c FROM runs WHERE verdict='PASS'"
        ).fetchone()["c"]

        return {
            "total_runs":  total,
            "done":        done,
            "failed":      failed,
            "running":     running,
            "pass_rate":   f"{pass_cnt/total*100:.0f}%" if total else "N/A",
            "avg_duration": f"{avg_dur:.0f}s",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        # Parse JSON fields
        for key in ("data", "config", "results"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d

    def cleanup_stale(self, max_age_hours: int = 0) -> int:
        """
        Mark 'running' records as 'crashed'.
        Called on server startup — if server restarted, no runs are actually running.
        max_age_hours=0 means clean ALL running records (default on startup).
        """
        import time
        if max_age_hours > 0:
            cutoff = time.time() - (max_age_hours * 3600)
            cur = self.conn.execute(
                "UPDATE runs SET status='crashed', verdict='FAIL' "
                "WHERE status='running' AND started_at < ?",
                (cutoff,),
            )
        else:
            # Clean ALL running records — server just restarted, nothing is running
            cur = self.conn.execute(
                "UPDATE runs SET status='crashed', verdict='FAIL' "
                "WHERE status='running'",
            )
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None