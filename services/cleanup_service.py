from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import Config
from repositories.job_repository import JobRepository


logger = logging.getLogger(__name__)


class CleanupService:
    def __init__(self, config: Config, repository: JobRepository) -> None:
        self.config = config
        self.repository = repository
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cleanup-worker", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def cleanup_once(self) -> None:
        self._cleanup_jobs()
        self._cleanup_orphans()

    def _run(self) -> None:
        interval_seconds = self.config.CLEANUP_INTERVAL_MINUTES * 60
        while not self._stop_event.wait(interval_seconds):
            self.cleanup_once()

    def _cleanup_jobs(self) -> None:
        candidates = self.repository.cleanup_candidates(
            self.config.CLEANUP_SUCCESS_AFTER_MINUTES,
            self.config.CLEANUP_FAILED_AFTER_HOURS,
        )
        for candidate in candidates:
            job = self.repository.get_job(str(candidate["id"]))
            if not job or job["status"] not in {"success", "failed"}:
                continue

            path = Path(str(job["stored_filepath"]))
            try:
                if path.exists():
                    path.unlink()
                self.repository.mark_deleted(str(job["id"]))
                logger.info("job_id=%s action=cleanup status=deleted message=file_removed", job["id"])
            except OSError:
                logger.exception("job_id=%s action=cleanup status=failed message=file_delete_failed", job["id"])

    def _cleanup_orphans(self) -> None:
        if not self.config.UPLOAD_DIR.exists():
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for path in self.config.UPLOAD_DIR.rglob("*"):
            if not path.is_file():
                continue

            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified_at > cutoff:
                continue

            resolved_path = path.resolve()
            if self.repository.stored_file_exists(resolved_path):
                continue

            try:
                resolved_path.unlink()
                logger.info("job_id=- action=cleanup status=deleted message=orphan_removed path=%s", resolved_path)
            except OSError:
                logger.exception("job_id=- action=cleanup status=failed message=orphan_delete_failed path=%s", resolved_path)

