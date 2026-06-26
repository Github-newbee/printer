from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from queue import Queue
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from config import Config
from repositories.job_repository import JobRepository
from services.cleanup_service import CleanupService
from services.errors import FileTooLargeError, ServiceError
from services.file_service import FileService
from services.job_service import JobService
from services.print_options import get_paper_size_options
from services.printer_service import PrinterService
from workers.print_worker import PrintWorker


def create_app() -> Flask:
    config = Config()
    ensure_runtime_dirs(config)
    configure_logging(config)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.max_file_size_bytes

    repository = JobRepository(config)
    repository.init_db()
    job_queue: Queue[str] = Queue()
    printer_service = PrinterService()
    file_service = FileService(config)
    job_service = JobService(repository, printer_service, file_service, job_queue)
    print_worker = PrintWorker(config, repository, job_queue)
    cleanup_service = CleanupService(config, repository)

    recovered_count = job_service.recover_startup_jobs(config.STARTUP_RECOVER_PRINTING_MODE)
    logging.getLogger(__name__).info(
        "job_id=- action=startup status=ok message=recovered_jobs count=%s",
        recovered_count,
    )
    print_worker.start()
    cleanup_service.start()

    app.extensions["print_service"] = {
        "config": config,
        "repository": repository,
        "job_service": job_service,
        "printer_service": printer_service,
        "print_worker": print_worker,
        "cleanup_service": cleanup_service,
        "job_queue": job_queue,
    }

    register_routes(app)
    register_error_handlers(app)
    return app


def ensure_runtime_dirs(config: Config) -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def configure_logging(config: Config) -> None:
    handler = RotatingFileHandler(config.LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not any(isinstance(existing, RotatingFileHandler) for existing in root_logger.handlers):
        root_logger.addHandler(handler)


def ok(data: Any, status: int = 200):
    return jsonify({"code": "OK", "message": "success", "data": data}), status


def fail(code: str, message: str, status: int):
    return jsonify({"code": code, "message": message, "data": None}), status


def register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        return render_template("upload.html")

    @app.get("/api/printers")
    def list_printers():
        printer_service: PrinterService = app.extensions["print_service"]["printer_service"]
        return ok({"items": printer_service.list_printers()})

    @app.get("/api/print-options")
    def get_print_options():
        return ok({"paper_sizes": get_paper_size_options()})

    @app.post("/api/print-jobs")
    def create_print_job():
        job_service: JobService = app.extensions["print_service"]["job_service"]
        file = request.files.get("file")
        if file is None:
            raise FileTooLargeError("PDF file is required")
        data = job_service.create_print_job(
            file=file,
            printer_name=request.form.get("printer_name", ""),
            user_name=request.form.get("user_name"),
            page_range=request.form.get("page_range"),
            copies=request.form.get("copies"),
            paper_size=request.form.get("paper_size"),
            orientation=request.form.get("orientation"),
        )
        return ok(data, status=201)

    @app.get("/api/print-jobs/<job_id>")
    def get_print_job(job_id: str):
        job_service: JobService = app.extensions["print_service"]["job_service"]
        return ok(job_service.get_job_detail(job_id))

    @app.get("/api/print-jobs")
    def list_print_jobs():
        job_service: JobService = app.extensions["print_service"]["job_service"]
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", request.args.get("limit", "50")))
        status = request.args.get("status")
        order_by = request.args.get("order_by", "created_at")
        order = request.args.get("order", "desc")
        return ok(job_service.list_jobs(status, page, page_size, order_by, order))

    @app.get("/health")
    def health():
        services = app.extensions["print_service"]
        repository: JobRepository = services["repository"]
        printer_service: PrinterService = services["printer_service"]
        print_worker: PrintWorker = services["print_worker"]
        job_queue: Queue[str] = services["job_queue"]
        config: Config = services["config"]

        errors: list[str] = []
        printer_count = 0
        try:
            printer_count = len(printer_service.list_printers())
        except RuntimeError as exc:
            errors.append(str(exc))

        db_writable = False
        try:
            db_writable = repository.check_writable()
        except Exception as exc:
            errors.append(f"db_not_writable: {exc}")

        sumatra_exists = config.SUMATRA_PATH.exists()
        if not sumatra_exists:
            errors.append("sumatra_not_found")

        data = {
            "status": "ok" if not errors else "degraded",
            "printer_count": printer_count,
            "queue_size": job_queue.qsize(),
            "worker_alive": print_worker.is_alive,
            "db_writable": db_writable,
            "sumatra_exists": sumatra_exists,
        }
        if errors:
            data["errors"] = errors
        return ok(data)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ServiceError)
    def handle_service_error(exc: ServiceError):
        return fail(exc.code, exc.message, exc.status_code)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_: RequestEntityTooLarge):
        return fail("FILE_TOO_LARGE", "File exceeds configured size limit", 400)

    @app.errorhandler(ValueError)
    def handle_value_error(exc: ValueError):
        return fail("BAD_REQUEST", str(exc), 400)


app = create_app()


if __name__ == "__main__":
    app.run(host=app.extensions["print_service"]["config"].HOST, port=app.extensions["print_service"]["config"].PORT)

