from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


@dataclass(frozen=True)
class Config:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _env_int("PORT", 5000)
    DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data\\print_service.db")
    DB_JOURNAL_MODE: str = os.getenv("DB_JOURNAL_MODE", "WAL")
    DB_BUSY_TIMEOUT_MS: int = _env_int("DB_BUSY_TIMEOUT_MS", 5000)
    UPLOAD_DIR: Path = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
    LOG_PATH: Path = BASE_DIR / os.getenv("LOG_PATH", "logs\\app.log")
    MAX_FILE_SIZE_MB: int = _env_int("MAX_FILE_SIZE_MB", 50)
    ALLOWED_EXTENSIONS: tuple[str, ...] = (".pdf",)
    CLEANUP_SUCCESS_AFTER_MINUTES: int = _env_int("CLEANUP_SUCCESS_AFTER_MINUTES", 10)
    CLEANUP_FAILED_AFTER_HOURS: int = _env_int("CLEANUP_FAILED_AFTER_HOURS", 24)
    CLEANUP_INTERVAL_MINUTES: int = _env_int("CLEANUP_INTERVAL_MINUTES", 10)
    SUMATRA_PATH: Path = BASE_DIR / os.getenv("SUMATRA_PATH", "tools\\SumatraPDF.exe")
    PRINT_COMMAND_TIMEOUT_SEC: int = _env_int("PRINT_COMMAND_TIMEOUT_SEC", 120)
    STARTUP_RECOVER_PRINTING_MODE: str = os.getenv("STARTUP_RECOVER_PRINTING_MODE", "fail")

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

