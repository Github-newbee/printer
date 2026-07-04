from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue

from config import Config
from repositories.job_repository import JobRepository
from services.print_options import get_sumatra_paper_setting


logger = logging.getLogger(__name__)


class PrintWorker:
    def __init__(self, config: Config, repository: JobRepository, job_queue: Queue[str]) -> None:
        self.config = config
        self.repository = repository
        self.job_queue = job_queue
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="print-worker", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self.job_queue.get(timeout=1)
            except Empty:
                continue

            try:
                self._print_job(job_id)
            finally:
                self.job_queue.task_done()

    def _print_job(self, job_id: str) -> None:
        if not self.repository.transition_to_printing(job_id):
            logger.info("job_id=%s action=print status=skipped message=not_pending", job_id)
            return

        job = self.repository.get_job(job_id)
        if not job:
            logger.error("job_id=%s action=print status=failed message=job_missing", job_id)
            return

        stored_path = Path(str(job["stored_filepath"]))
        if not stored_path.exists():
            self.repository.mark_failed(job_id, "stored_file_missing")
            logger.error("job_id=%s action=print status=failed message=stored_file_missing", job_id)
            return

        if not self.config.SUMATRA_PATH.exists():
            self.repository.mark_failed(job_id, "sumatra_not_found")
            logger.error("job_id=%s action=print status=failed message=sumatra_not_found", job_id)
            return

        command = [
            str(self.config.SUMATRA_PATH),
            "-print-to",
            str(job["printer_name"]),
        ]
        try:
            print_settings = self._print_settings(job)
        except ValueError as exc:
            self.repository.mark_failed(job_id, str(exc))
            logger.error("job_id=%s action=print status=failed message=%s", job_id, exc)
            return
        if print_settings:
            command.extend(["-print-settings", print_settings])
        command.extend(["-silent", str(stored_path)])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.config.PRINT_COMMAND_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.repository.mark_failed(job_id, "print_command_timeout")
            logger.error("job_id=%s action=print status=failed message=print_command_timeout", job_id)
            return
        except OSError as exc:
            self.repository.mark_failed(job_id, f"print_command_error: {exc}")
            logger.exception("job_id=%s action=print status=failed message=print_command_error", job_id)
            return

        if result.returncode != 0:
            error_output = (result.stderr or result.stdout or "print_command_failed").strip()
            self.repository.mark_failed(job_id, error_output[:1000])
            logger.error("job_id=%s action=print status=failed message=%s", job_id, error_output)
            return

        self.repository.mark_submitted(job_id)
        self.repository.mark_success(job_id)
        logger.info("job_id=%s action=print status=success message=submitted_to_spooler", job_id)

    def _print_settings(self, job: dict[str, object]) -> str | None:
        settings: list[str] = []
        page_range = str(job.get("page_range") or "").strip()
        if page_range:
            settings.append(page_range)

        copies = int(job.get("copies") or 1)
        if copies > 1:
            settings.append(f"{copies}x")

        orientation = str(job.get("orientation") or "").strip().lower()
        if orientation == "portrait":
            settings.append("disable-auto-rotation")
        elif orientation == "landscape":
            settings.extend(["landscape", "disable-auto-rotation"])

        paper_setting = get_sumatra_paper_setting(job.get("paper_size") if job.get("paper_size") else None)
        if paper_setting:
            settings.append(paper_setting)

        return ",".join(settings) if settings else None

