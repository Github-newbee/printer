from __future__ import annotations


class ServiceError(Exception):
    code = "SERVICE_ERROR"
    status_code = 500

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class InvalidFileTypeError(ServiceError):
    code = "INVALID_FILE_TYPE"
    status_code = 400


class FileTooLargeError(ServiceError):
    code = "FILE_TOO_LARGE"
    status_code = 400


class PrinterNotFoundError(ServiceError):
    code = "PRINTER_NOT_FOUND"
    status_code = 400


class UploadFailedError(ServiceError):
    code = "UPLOAD_FAILED"
    status_code = 500


class QueueFailedError(ServiceError):
    code = "QUEUE_FAILED"
    status_code = 500


class PrintFailedError(ServiceError):
    code = "PRINT_FAILED"
    status_code = 500


class JobNotFoundError(ServiceError):
    code = "JOB_NOT_FOUND"
    status_code = 404

