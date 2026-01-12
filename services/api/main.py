import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.auth import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    get_user,
    revoke_refresh_token,
    rotate_refresh_token,
)
from shared.celery_app import celery_app
from shared.config import get_settings
from shared.db import get_session_factory
from shared.logging import configure_logging
from shared.models import AuthIdentity, Collection, Job, Problem, SmsOtp, User
from shared.redis import get_redis
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
SessionLocal = get_session_factory()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="missing token")
    token = auth_header.replace("Bearer ", "")
    try:
        user_id = decode_access_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user


@app.get("/healthz")
def healthz(request: Request):
    return api_response(request, data="ok")


@app.post("/api/v1/auth/sms/send")
def sms_send(request: Request, body: SmsSendRequest, db: Session = Depends(get_db)):
    redis_client = get_redis()
    phone_key = f"sms:phone:{body.phone}"
    ip = request.client.host if request.client else "unknown"
    ip_key = f"sms:ip:{ip}:{datetime.utcnow().strftime('%Y%m%d%H')}"

    if redis_client.get(phone_key):
        raise HTTPException(status_code=429, detail="rate limit")
    if redis_client.incr(ip_key) > settings.sms_ip_rate_limit_per_hour:
        raise HTTPException(status_code=429, detail="rate limit")
    redis_client.expire(ip_key, 3600)

    code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expires_at = datetime.utcnow() + timedelta(seconds=settings.sms_code_expire_seconds)
    otp = SmsOtp(phone=body.phone, code_hash=code_hash, expires_at=expires_at, ip=ip)
    db.add(otp)
    db.commit()

    redis_client.setex(phone_key, settings.sms_phone_rate_limit_seconds, "1")
    logger.info("mock sms send", extra={"phone": body.phone, "code": code})
    return api_response(request, data={"sent": True})


def _verify_sms_code(db: Session, phone: str, code: str) -> Optional[SmsOtp]:
    redis_client = get_redis()
    otp = (
        db.query(SmsOtp)
        .filter(SmsOtp.phone == phone, SmsOtp.consumed_at.is_(None))
        .order_by(SmsOtp.created_at.desc())
        .first()
    )
    if not otp:
        return None
    if otp.expires_at < datetime.utcnow():
        return None
    attempt_key = f"sms:attempt:{otp.id}"
    attempts = int(redis_client.get(attempt_key) or 0)
    if attempts >= 5:
        return None
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if otp.code_hash != code_hash:
        redis_client.incr(attempt_key)
        redis_client.expire(attempt_key, settings.sms_code_expire_seconds)
        return None
    otp.consumed_at = datetime.utcnow()
    db.add(otp)
    db.commit()
    redis_client.delete(attempt_key)
    return otp


def _get_or_create_user_for_phone(db: Session, phone: str) -> User:
    identity = (
        db.query(AuthIdentity)
        .filter(AuthIdentity.provider == "phone", AuthIdentity.provider_uid == phone)
        .first()
    )
    if identity:
        return db.query(User).filter(User.id == identity.user_id).first()
    user = User()
    db.add(user)
    db.commit()
    identity = AuthIdentity(user_id=user.id, provider="phone", provider_uid=phone)
    db.add(identity)
    db.commit()
    return user


def _tokens_for_user(db: Session, user: User) -> Dict[str, Any]:
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(db, str(user.id))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": str(user.id), "nickname": user.nickname, "avatar_url": user.avatar_url},
    }


@app.post("/api/v1/auth/sms/verify")
def sms_verify(request: Request, body: SmsVerifyRequest, db: Session = Depends(get_db)):
    otp = _verify_sms_code(db, body.phone, body.code)
    if not otp:
        raise HTTPException(status_code=400, detail="invalid code")
    user = _get_or_create_user_for_phone(db, body.phone)
    return api_response(request, data=_tokens_for_user(db, user))


@app.post("/api/v1/auth/refresh")
def refresh_token(request: Request, body: RefreshRequest, db: Session = Depends(get_db)):
    result = rotate_refresh_token(db, body.refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="invalid refresh token")
    new_token, user_id = result
    access_token = create_access_token(user_id)
    return api_response(request, data={"access_token": access_token, "refresh_token": new_token})


@app.post("/api/v1/auth/logout")
def logout(request: Request, body: LogoutRequest, db: Session = Depends(get_db)):
    revoke_refresh_token(db, body.refresh_token)
    return api_response(request, data={"revoked": True})


@app.get("/api/v1/me")
def me(request: Request, user: User = Depends(get_current_user)):
    return api_response(request, data={"id": str(user.id), "nickname": user.nickname, "avatar_url": user.avatar_url})


@app.get("/api/v1/auth/wechat/web/authorize")
def wechat_authorize(request: Request):
    state = secrets.token_urlsafe(16)
    redis_client = get_redis()
    redis_client.setex(f"wechat_state:{state}", 300, "1")
    redirect_url = (
        "https://open.weixin.qq.com/connect/qrconnect"
        f"?appid={settings.wechat_app_id}&redirect_uri=http://localhost:8000/api/v1/auth/wechat/web/callback"
        f"&response_type=code&scope=snsapi_login&state={state}#wechat_redirect"
    )
    return JSONResponse(status_code=302, headers={"Location": redirect_url})


@app.get("/api/v1/auth/wechat/web/callback")
def wechat_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    redis_client = get_redis()
    if not redis_client.get(f"wechat_state:{state}"):
        raise HTTPException(status_code=400, detail="invalid state")
    redis_client.delete(f"wechat_state:{state}")

    if settings.wechat_mock:
        provider_uid = f"mock-{code}"
        union_id = None
    else:
        provider_uid = f"wechat-{code}"
        union_id = None

    identity = (
        db.query(AuthIdentity)
        .filter(AuthIdentity.provider == "wechat_web", AuthIdentity.provider_uid == provider_uid)
        .first()
    )
    if identity:
        user = db.query(User).filter(User.id == identity.user_id).first()
    else:
        user = User()
        db.add(user)
        db.commit()
        identity = AuthIdentity(user_id=user.id, provider="wechat_web", provider_uid=provider_uid, union_id=union_id)
        db.add(identity)
        db.commit()

    one_time_code = secrets.token_urlsafe(16)
    redis_client.setex(f"wechat_exchange:{one_time_code}", 300, str(user.id))
    redirect_url = f"{settings.frontend_auth_callback_url}?code={one_time_code}"
    return JSONResponse(status_code=302, headers={"Location": redirect_url})


@app.post("/api/v1/auth/exchange")
def wechat_exchange(request: Request, body: WechatExchangeRequest, db: Session = Depends(get_db)):
    redis_client = get_redis()
    user_id = redis_client.get(f"wechat_exchange:{body.one_time_code}")
    if not user_id:
        raise HTTPException(status_code=400, detail="invalid code")
    redis_client.delete(f"wechat_exchange:{body.one_time_code}")
    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        raise HTTPException(status_code=400, detail="user not found")
    return api_response(request, data=_tokens_for_user(db, user))


@app.post("/api/v1/collections")
def create_collection(
    request: Request, body: CollectionCreateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    collection = Collection(user_id=user.id, name=body.name)
    db.add(collection)
    db.commit()
    return api_response(request, data={"id": str(collection.id), "name": collection.name})


@app.get("/api/v1/collections")
def list_collections(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collections = db.query(Collection).filter(Collection.user_id == user.id).all()
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
    request: Request, collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
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
    user: User = Depends(get_current_user),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
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
    request: Request, collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(collection)
    db.commit()
    return api_response(request, data={"deleted": True})


@app.post("/api/v1/uploads/presign")
def upload_presign(
    request: Request, body: UploadPresignRequest, user: User = Depends(get_current_user)
):
    data = build_presign_response(str(user.id), body.filename)
    return api_response(request, data=data)


@app.post("/api/v1/uploads/direct")
def upload_direct(
    request: Request,
    object_key: str = Query(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if not object_key.startswith(f"user/{user.id}/"):
        raise HTTPException(status_code=403, detail="invalid object key")
    local_path = get_local_path(object_key)
    os_dir = local_path.rsplit("/", 1)[0]
    os.makedirs(os_dir, exist_ok=True)
    with open(local_path, "wb") as buffer:
        buffer.write(file.file.read())
    return api_response(request, data={"object_key": object_key, "url": get_public_url(object_key)})


@app.post("/api/v1/uploads/complete")
def upload_complete(
    request: Request, body: UploadCompleteRequest, user: User = Depends(get_current_user)
):
    if not body.object_key.startswith(f"user/{user.id}/"):
        raise HTTPException(status_code=403, detail="invalid object key")
    return api_response(request, data={"url": get_public_url(body.object_key)})


@app.post("/api/v1/problems")
def create_problem(
    request: Request, body: ProblemCreateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == body.collection_id, Collection.user_id == user.id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="collection not found")
    problem = Problem(
        user_id=user.id,
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
    user: User = Depends(get_current_user),
):
    query = db.query(Problem).filter(
        Problem.collection_id == collection_id, Problem.user_id == user.id
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
    request: Request, problem_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == user.id).first()
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
    user: User = Depends(get_current_user),
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == user.id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    if problem.version != body.version:
        raise HTTPException(status_code=409, detail="version mismatch")
    if body.collection_id:
        collection = (
            db.query(Collection)
            .filter(Collection.id == body.collection_id, Collection.user_id == user.id)
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
    request: Request, problem_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == user.id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(problem)
    db.commit()
    return api_response(request, data={"deleted": True})


@app.get("/api/v1/jobs/{job_id}")
def get_job(
    request: Request, job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
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
    user: User = Depends(get_current_user),
):
    problem = db.query(Problem).filter(Problem.id == problem_id, Problem.user_id == user.id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="not found")
    job = None
    if body.idempotency_key:
        job = (
            db.query(Job)
            .filter(
                Job.user_id == user.id,
                Job.type == "OCR",
                Job.idempotency_key == body.idempotency_key,
            )
            .first()
        )
    if not job:
        job = Job(
            user_id=user.id,
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
    user: User = Depends(get_current_user),
):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="not found")
    job = None
    if body.idempotency_key:
        job = (
            db.query(Job)
            .filter(
                Job.user_id == user.id,
                Job.type == "PDF_EXPORT",
                Job.idempotency_key == body.idempotency_key,
            )
            .first()
        )
    if not job:
        job = Job(
            user_id=user.id,
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
