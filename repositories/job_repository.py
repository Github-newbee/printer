from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from config import Config
from services.print_options import DEFAULT_PAPER_SIZE


STATUSES = {"pending", "printing", "submitted", "success", "failed", "deleted"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class JobRepository:
    def __init__(self, config: Config) -> None:
        self.config = config

    def init_db(self) -> None:
        self.config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS print_jobs (
                  id TEXT PRIMARY KEY,
                  user_id TEXT,
                  user_name TEXT,
                  source_filename TEXT NOT NULL,
                  stored_filepath TEXT NOT NULL,
                  file_size_bytes INTEGER NOT NULL,
                  printer_name TEXT NOT NULL,
                  page_range TEXT,
                  copies INTEGER NOT NULL DEFAULT 1,
                  paper_size TEXT NOT NULL DEFAULT '{DEFAULT_PAPER_SIZE}',
                  orientation TEXT NOT NULL DEFAULT 'portrait',
                  status TEXT NOT NULL,
                  error_message TEXT,
                  created_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  cleaned_at TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(print_jobs)").fetchall()
            }
            if "page_range" not in columns:
                conn.execute("ALTER TABLE print_jobs ADD COLUMN page_range TEXT")
            if "copies" not in columns:
                conn.execute("ALTER TABLE print_jobs ADD COLUMN copies INTEGER NOT NULL DEFAULT 1")
            if "paper_size" not in columns:
                conn.execute(
                    f"ALTER TABLE print_jobs ADD COLUMN paper_size TEXT NOT NULL DEFAULT '{DEFAULT_PAPER_SIZE}'"
                )
            if "orientation" not in columns:
                conn.execute("ALTER TABLE print_jobs ADD COLUMN orientation TEXT NOT NULL DEFAULT 'portrait'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_created_at ON print_jobs(created_at)")
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            self.config.DB_PATH,
            timeout=self.config.DB_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=True,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA journal_mode={self.config.DB_JOURNAL_MODE}")
            conn.execute(f"PRAGMA busy_timeout={self.config.DB_BUSY_TIMEOUT_MS}")
            yield conn
        finally:
            conn.close()

    def create_job(self, job: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO print_jobs (
                  id, user_id, user_name, source_filename, stored_filepath,
                  file_size_bytes, printer_name, page_range, copies, paper_size, orientation, status, error_message,
                  created_at, started_at, finished_at, cleaned_at
                ) VALUES (
                  :id, :user_id, :user_name, :source_filename, :stored_filepath,
                  :file_size_bytes, :printer_name, :page_range, :copies, :paper_size, :orientation, :status, :error_message,
                  :created_at, :started_at, :finished_at, :cleaned_at
                )
                """,
                job,
            )
            conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_jobs(
        self,
        status: str | None,
        page: int,
        page_size: int,
        order_by: str,
        order: str,
    ) -> tuple[list[dict[str, Any]], int]:
        allowed_order_by = {"created_at", "started_at", "finished_at", "status"}
        if order_by not in allowed_order_by:
            order_by = "created_at"
        order_sql = "ASC" if order.lower() == "asc" else "DESC"
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size

        where = ""
        params: list[Any] = []
        if status:
            where = "WHERE status = ?"
            params.append(status)

        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM print_jobs {where}", params).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM print_jobs
                {where}
                ORDER BY {order_by} {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
            return [dict(row) for row in rows], total

    def transition_to_printing(self, job_id: str) -> bool:
        with self.connect() as conn:
            conn.execute("BEGIN")
            cursor = conn.execute(
                """
                UPDATE print_jobs
                SET status = 'printing', started_at = ?, error_message = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (iso_now(), job_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    def mark_submitted(self, job_id: str) -> None:
        self._update_status(job_id, "submitted", error_message=None, set_finished=False)

    def mark_success(self, job_id: str) -> None:
        self._update_status(job_id, "success", error_message=None, set_finished=True)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        self._update_status(job_id, "failed", error_message=error_message, set_finished=True)

    def mark_deleted(self, job_id: str) -> None:
        now = iso_now()
        with self.connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                UPDATE print_jobs
                SET status = 'deleted', cleaned_at = ?
                WHERE id = ? AND status IN ('success', 'failed')
                """,
                (now, job_id),
            )
            conn.commit()

    def _update_status(
        self,
        job_id: str,
        status: str,
        error_message: str | None,
        set_finished: bool,
    ) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unsupported job status: {status}")
        finished_at = iso_now() if set_finished else None
        with self.connect() as conn:
            conn.execute("BEGIN")
            if set_finished:
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = ?, error_message = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (status, error_message, finished_at, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (status, error_message, job_id),
                )
            conn.commit()

    def recover_startup_jobs(self, printing_mode: str) -> list[str]:
        with self.connect() as conn:
            conn.execute("BEGIN")
            if printing_mode == "retry":
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = 'pending', started_at = NULL, error_message = NULL
                    WHERE status = 'printing'
                    """
                )
            elif printing_mode == "fail":
                conn.execute(
                    """
                    UPDATE print_jobs
                    SET status = 'failed', finished_at = ?, error_message = 'service_restart'
                    WHERE status = 'printing'
                    """,
                    (iso_now(),),
                )
            else:
                raise ValueError("STARTUP_RECOVER_PRINTING_MODE must be 'fail' or 'retry'")

            rows = conn.execute("SELECT id FROM print_jobs WHERE status = 'pending' ORDER BY created_at ASC").fetchall()
            conn.commit()
            return [row["id"] for row in rows]

    def cleanup_candidates(self, success_after_minutes: int, failed_after_hours: int) -> list[dict[str, Any]]:
        success_before = utc_now() - timedelta(minutes=success_after_minutes)
        failed_before = utc_now() - timedelta(hours=failed_after_hours)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM print_jobs
                WHERE cleaned_at IS NULL
                  AND (
                    (status = 'success' AND finished_at IS NOT NULL AND finished_at <= ?)
                    OR
                    (status = 'failed' AND finished_at IS NOT NULL AND finished_at <= ?)
                  )
                """,
                (success_before.isoformat(), failed_before.isoformat()),
            ).fetchall()
            return [dict(row) for row in rows]

    def stored_file_exists(self, file_path: Path) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM print_jobs WHERE stored_filepath = ? LIMIT 1",
                (str(file_path),),
            ).fetchone()
            return row is not None

    def check_writable(self) -> bool:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE print_jobs SET id = id WHERE 1 = 0")
            conn.rollback()
            return True

