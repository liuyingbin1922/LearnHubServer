import logging
import os
import secrets
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from services.api.deps.auth import get_current_user_id, require_auth
from services.api.deps.db import get_db
from services.api.middleware.auth import AuthMiddleware
from shared.celery_app import celery_app
from shared.config import get_settings
from shared.logging import configure_logging
from shared.models import Collection, Job, Problem, User
from shared.schemas import (
    CollectionCreateRequest,
    CollectionUpdateRequest,
    ExportPdfRequest,
    LogoutRequest,
    OcrRequest,
    ProblemCreateRequest,
    ProblemUpdateRequest,
    RefreshRequest,
    SmsSendRequest,
    SmsVerifyRequest,
    UploadCompleteRequest,
    UploadPresignRequest,
    WechatExchangeRequest,
)
from shared.storage import build_presign_response, ensure_storage_root, get_local_path, get_public_url


configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI()
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

ensure_storage_root()
app.mount("/media", StaticFiles(directory=settings.storage_root), name="media")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or secrets.token_hex(8)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


def api_response(request: Request, data: Any = None, code: int = 0, message: str = "ok") -> JSONResponse:
    payload = {"code": code, "message": message, "data": data, "request_id": request.state.request_id}
    return JSONResponse(payload)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return api_response(request, data=None, code=exc.status_code, message=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return api_response(request, data={"errors": exc.errors()}, code=400, message="validation_error")


def deprecated_auth_response(request: Request):
    return api_response(request, data=None, code=410, message="Auth handled by Better Auth; use /api/auth")


@app.get("/healthz")
def healthz(request: Request):
    return api_response(request, data="ok")


@app.post("/api/v1/auth/sms/send")
def sms_send(request: Request, body: SmsSendRequest):
    return deprecated_auth_response(request)


@app.post("/api/v1/auth/sms/verify")
def sms_verify(request: Request, body: SmsVerifyRequest):
    return deprecated_auth_response(request)


@app.post("/api/v1/auth/refresh")
def refresh_token(request: Request, body: RefreshRequest):
    return deprecated_auth_response(request)


@app.post("/api/v1/auth/logout")
def logout(request: Request, body: LogoutRequest):
    return deprecated_auth_response(request)


@app.get("/api/v1/me")
def me(request: Request, user_id: str = Depends(require_auth), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="not found")
    claims = getattr(request.state, "claims", {})
    return api_response(
        request,
        data={
            "id": str(user.id),
            "nickname": user.nickname,
            "avatar_url": user.avatar_url,
            "email": claims.get("email"),
        },
    )


@app.get("/api/v1/auth/wechat/web/authorize")
def wechat_authorize(request: Request):
    return deprecated_auth_response(request)


@app.get("/api/v1/auth/wechat/web/callback")
def wechat_callback(request: Request, code: str, state: str):
    return deprecated_auth_response(request)


@app.post("/api/v1/auth/exchange")
def wechat_exchange(request: Request, body: WechatExchangeRequest):
    return deprecated_auth_response(request)


@app.post("/api/v1/collections")
def create_collection(
    request: Request,
    body: CollectionCreateRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    collection = Collection(user_id=UUID(user_id), name=body.name)
    db.add(collection)
    db.commit()
    return api_response(request, data={"id": str(collection.id), "name": collection.name})


@app.get("/api/v1/collections")
def list_collections(request: Request, db: Session = Depends(get_db), user_id: str = Depends(require_auth)):
    collections = db.query(Collection).filter(Collection.user_id == UUID(user_id)).all()
    collection_ids = [c.id for c in collections]
    counts = (
        db.query(Problem.collection_id, func.count(Problem.id))
        .filter(Problem.collection_id.in_(collection_ids))
        .group_by(Problem.collection_id)
        .all()
    )
    count_map = {str(cid): count for cid, count in counts}
    data = [
        {"id": str(c.id), "name": c.name, "problem_count": count_map.get(str(c.id), 0)}
        for c in collections
    ]
    return api_response(request, data=data)


@app.get("/api/v1/collections/{collection_id}")
def get_collection(
    request: Request,
    collection_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == UUID(user_id))
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    return api_response(request, data={"id": str(collection.id), "name": collection.name})


@app.patch("/api/v1/collections/{collection_id}")
def update_collection(
    request: Request,
    collection_id: str,
    body: CollectionUpdateRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == UUID(user_id))
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    if body.name:
        collection.name = body.name
    collection.updated_at = datetime.utcnow()
    db.add(collection)
    db.commit()
    return api_response(request, data={"id": str(collection.id), "name": collection.name})


@app.delete("/api/v1/collections/{collection_id}")
def delete_collection(
    request: Request, collection_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_auth)
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == UUID(user_id))
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(collection)
    db.commit()
    return api_response(request, data={"deleted": True})


@app.post("/api/v1/uploads/presign")
def upload_presign(
    request: Request, body: UploadPresignRequest, user_id: str = Depends(require_auth)
):
    data = build_presign_response(user_id, body.filename)
    return api_response(request, data=data)


@app.post("/api/v1/uploads/direct")
def upload_direct(
    request: Request,
    object_key: str = Query(...),
    file: UploadFile = File(...),
    user_id: str = Depends(require_auth),
):
    if not object_key.startswith(f"user/{user_id}/"):
        raise HTTPException(status_code=403, detail="invalid object key")
    local_path = get_local_path(object_key)
    os_dir = local_path.rsplit("/", 1)[0]
    os.makedirs(os_dir, exist_ok=True)
    with open(local_path, "wb") as buffer:
        buffer.write(file.file.read())
    return api_response(request, data={"object_key": object_key, "url": get_public_url(object_key)})


@app.post("/api/v1/uploads/complete")
def upload_complete(
    request: Request, body: UploadCompleteRequest, user_id: str = Depends(require_auth)
):
    if not body.object_key.startswith(f"user/{user_id}/"):
        raise HTTPException(status_code=403, detail="invalid object key")
    return api_response(request, data={"url": get_public_url(body.object_key)})


@app.post("/api/v1/problems")
def create_problem(
    request: Request,
    body: ProblemCreateRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == body.collection_id, Collection.user_id == UUID(user_id))
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="collection not found")
    problem = Problem(
        user_id=UUID(user_id),
        collection_id=collection.id,
        status="DRAFT",
        original_image_url=body.original_image_url,
        cropped_image_url=body.cropped_image_url,
        order_index=body.order_index or 0,
    )
    db.add(problem)
    db.commit()
    return api_response(request, data={"id": str(problem.id), "status": problem.status})


@app.get("/api/v1/collections/{collection_id}/problems")
def list_problems(
    request: Request,
    collection_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    updated_after: Optional[str] = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    query = db.query(Problem).filter(
        Problem.collection_id == collection_id, Problem.user_id == UUID(user_id)
    )
    if updated_after:
        query = query.filter(Problem.updated_at > datetime.fromisoformat(updated_after))
    problems = query.order_by(Problem.updated_at.desc()).offset(offset).limit(limit).all()
    data = [
        {
            "id": str(p.id),
            "status": p.status,
            "original_image_url": p.original_image_url,
            "cropped_image_url": p.cropped_image_url,
            "ocr_text": p.ocr_text,
            "note": p.note,
            "tags": p.tags,
            "order_index": p.order_index,
            "version": p.version,
        }
        for p in problems
    ]
    return api_response(request, data=data)


@app.get("/api/v1/problems/{problem_id}")
def get_problem(
    request: Request, problem_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_auth)
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == UUID(user_id)).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    data = {
        "id": str(problem.id),
        "status": problem.status,
        "original_image_url": problem.original_image_url,
        "cropped_image_url": problem.cropped_image_url,
        "ocr_text": problem.ocr_text,
        "note": problem.note,
        "tags": problem.tags,
        "order_index": problem.order_index,
        "version": problem.version,
    }
    return api_response(request, data=data)


@app.patch("/api/v1/problems/{problem_id}")
def update_problem(
    request: Request,
    problem_id: str,
    body: ProblemUpdateRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == UUID(user_id)).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    if problem.version != body.version:
        raise HTTPException(status_code=409, detail="version mismatch")
    if body.collection_id:
        collection = (
            db.query(Collection)
            .filter(Collection.id == body.collection_id, Collection.user_id == UUID(user_id))
            .first()
        )
        if not collection:
            raise HTTPException(status_code=404, detail="collection not found")
        problem.collection_id = collection.id
    if body.ocr_text is not None:
        problem.ocr_text = body.ocr_text
    if body.note is not None:
        problem.note = body.note
    if body.tags is not None:
        problem.tags = body.tags
    if body.order_index is not None:
        problem.order_index = body.order_index
    problem.version += 1
    problem.updated_at = datetime.utcnow()
    db.add(problem)
    db.commit()
    return api_response(request, data={"id": str(problem.id), "version": problem.version})


@app.delete("/api/v1/problems/{problem_id}")
def delete_problem(
    request: Request, problem_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_auth)
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == UUID(user_id)).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(problem)
    db.commit()
    return api_response(request, data={"deleted": True})


@app.get("/api/v1/jobs/{job_id}")
def get_job(
    request: Request, job_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_auth)
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == UUID(user_id)).first()
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    data = {"status": job.status, "result": job.result, "error_message": job.error_message}
    return api_response(request, data=data)


@app.post("/api/v1/problems/{problem_id}/ocr")
def trigger_ocr(
    request: Request,
    problem_id: str,
    body: OcrRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == UUID(user_id)).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    job = None
    if body.idempotency_key:
        job = (
            db.query(Job)
            .filter(
                Job.user_id == UUID(user_id),
                Job.type == "OCR",
                Job.idempotency_key == body.idempotency_key,
            )
            .first()
        )
    if not job:
        job = Job(
            user_id=UUID(user_id),
            type="OCR",
            status="PENDING",
            target_id=problem.id,
            idempotency_key=body.idempotency_key,
        )
        db.add(job)
        problem.status = "OCR_PENDING"
        problem.updated_at = datetime.utcnow()
        db.commit()
        image_url = body.image_url or problem.original_image_url
        celery_app.send_task(
            "services.worker.tasks.ocr_task",
            args=[str(problem.id), str(job.id), image_url],
        )
    return api_response(request, data={"job_id": str(job.id)})


@app.post("/api/v1/collections/{collection_id}/export_pdf")
def export_pdf(
    request: Request,
    collection_id: str,
    body: ExportPdfRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_auth),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == UUID(user_id))
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    job = None
    if body.idempotency_key:
        job = (
            db.query(Job)
            .filter(
                Job.user_id == UUID(user_id),
                Job.type == "PDF_EXPORT",
                Job.idempotency_key == body.idempotency_key,
            )
            .first()
        )
    if not job:
        job = Job(
            user_id=UUID(user_id),
            type="PDF_EXPORT",
            status="PENDING",
            target_id=collection.id,
            idempotency_key=body.idempotency_key,
        )
        db.add(job)
        db.commit()
        celery_app.send_task(
            "services.worker.tasks.export_pdf_task",
            args=[str(collection.id), str(job.id), body.options or {}],
        )
    return api_response(request, data={"job_id": str(job.id)})
