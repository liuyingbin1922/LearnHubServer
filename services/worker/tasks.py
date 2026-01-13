import logging
import os
from datetime import datetime
from typing import Any, Dict

import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from shared.celery_app import celery_app
from shared.config import get_settings
from shared.db import get_session_factory
from shared.models import Job, Problem, Collection
from shared.storage import ensure_storage_root, get_local_path, get_public_url


logger = logging.getLogger(__name__)
settings = get_settings()
SessionLocal = get_session_factory()
ensure_storage_root()


def _update_job(session: Session, job_id: str, status: str, result: Dict[str, Any] | None = None, error: str | None = None):
    job = session.query(Job).filter(Job.id == job_id).first()
    if not job:
        return
    job.status = status
    job.result = result
    job.error_message = error
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()


@celery_app.task(name="services.worker.tasks.ocr_task")
def ocr_task(problem_id: str, job_id: str, image_url: str):
    session = SessionLocal()
    try:
        _update_job(session, job_id, "RUNNING")
        problem = session.query(Problem).filter(Problem.id == problem_id).first()
        if not problem:
            raise ValueError("problem not found")
        if image_url.startswith(settings.public_base_url):
            relative_key = image_url.replace(f"{settings.public_base_url}/", "")
            image_path = get_local_path(relative_key)
            with open(image_path, "rb") as file:
                content = file.read()
        else:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            content = response.content
        ocr_text = "mock ocr text"
        ocr_raw = {"length": len(content), "source": image_url}
        problem.ocr_text = ocr_text
        problem.ocr_raw = ocr_raw
        problem.status = "OCR_DONE"
        problem.updated_at = datetime.utcnow()
        session.add(problem)
        session.commit()
        _update_job(session, job_id, "SUCCESS", result={"problem_id": problem_id, "ocr_text": ocr_text})
    except Exception as exc:  # noqa: BLE001
        problem = session.query(Problem).filter(Problem.id == problem_id).first()
        if problem:
            problem.status = "OCR_FAILED"
            problem.updated_at = datetime.utcnow()
            session.add(problem)
            session.commit()
        _update_job(session, job_id, "FAILED", error=str(exc))
        logger.exception("ocr failed")
    finally:
        session.close()


@celery_app.task(name="services.worker.tasks.export_pdf_task")
def export_pdf_task(collection_id: str, job_id: str, options: Dict[str, Any]):
    session = SessionLocal()
    try:
        _update_job(session, job_id, "RUNNING")
        collection = session.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise ValueError("collection not found")
        problems = (
            session.query(Problem)
            .filter(Problem.collection_id == collection.id)
            .order_by(Problem.order_index.asc(), Problem.created_at.asc())
            .all()
        )
        object_key = f"user/{collection.user_id}/exports/{collection.id}.pdf"
        local_path = get_local_path(object_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        pdf = canvas.Canvas(local_path, pagesize=letter)
        for problem in problems:
            pdf.drawString(72, 720, f"Problem {problem.id}")
            if problem.ocr_text:
                pdf.drawString(72, 700, problem.ocr_text[:200])
            pdf.showPage()
        pdf.save()
        pdf_url = get_public_url(object_key)
        _update_job(session, job_id, "SUCCESS", result={"pdf_url": pdf_url, "collection_id": collection_id})
    except Exception as exc:  # noqa: BLE001
        _update_job(session, job_id, "FAILED", error=str(exc))
        logger.exception("pdf export failed")
    finally:
        session.close()
