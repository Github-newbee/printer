from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config import Config
from services.errors import FileTooLargeError, InvalidFileTypeError, UploadFailedError


PDF_MAGIC = b"%PDF-"


class FileService:
    def __init__(self, config: Config) -> None:
        self.config = config

    def save_upload(self, file: FileStorage, job_id: str) -> tuple[str, Path, int]:
        source_filename = self._source_filename(file)
        self._validate_extension(source_filename)

        day_dir = self.config.UPLOAD_DIR / datetime.now().strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        stored_path = day_dir / f"{job_id}_{uuid4().hex[:8]}.pdf"

        total_size = 0
        try:
            with stored_path.open("wb") as target:
                header = file.stream.read(len(PDF_MAGIC))
                if header != PDF_MAGIC:
                    raise InvalidFileTypeError("Uploaded file is not a PDF")
                target.write(header)
                total_size += len(header)

                while True:
                    chunk = file.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > self.config.max_file_size_bytes:
                        raise FileTooLargeError(f"File exceeds {self.config.MAX_FILE_SIZE_MB} MB")
                    target.write(chunk)
        except (InvalidFileTypeError, FileTooLargeError):
            stored_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            stored_path.unlink(missing_ok=True)
            raise UploadFailedError("Failed to save uploaded file") from exc

        return source_filename, stored_path.resolve(), total_size

    def _source_filename(self, file: FileStorage) -> str:
        raw_filename = file.filename or ""
        safe_name = secure_filename(raw_filename)
        if not safe_name:
            raise InvalidFileTypeError("File name is required")
        return raw_filename

    def _validate_extension(self, filename: str) -> None:
        suffix = Path(filename).suffix.lower()
        if suffix not in self.config.ALLOWED_EXTENSIONS:
            raise InvalidFileTypeError("Only PDF files are allowed")

