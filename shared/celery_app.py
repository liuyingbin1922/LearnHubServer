from celery import Celery

from shared.config import get_settings


settings = get_settings()

celery_app = Celery(
    "learnhub",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_routes = {
    "services.worker.tasks.ocr_task": {"queue": "ocr"},
    "services.worker.tasks.export_pdf_task": {"queue": "pdf"},
}
