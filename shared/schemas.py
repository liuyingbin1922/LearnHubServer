from typing import Any, Optional
from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None
    request_id: str


class SmsSendRequest(BaseModel):
    phone: str


class SmsVerifyRequest(BaseModel):
    phone: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class WechatExchangeRequest(BaseModel):
    one_time_code: str


class CollectionCreateRequest(BaseModel):
    name: str


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None


class ProblemCreateRequest(BaseModel):
    collection_id: str
    original_image_url: str
    cropped_image_url: Optional[str] = None
    order_index: Optional[int] = 0


class ProblemUpdateRequest(BaseModel):
    ocr_text: Optional[str] = None
    note: Optional[str] = None
    tags: Optional[Any] = None
    order_index: Optional[int] = None
    collection_id: Optional[str] = None
    version: int


class UploadPresignRequest(BaseModel):
    filename: str
    content_type: str
    size: int


class UploadCompleteRequest(BaseModel):
    object_key: str


class OcrRequest(BaseModel):
    image_url: Optional[str] = None
    idempotency_key: Optional[str] = None


class ExportPdfRequest(BaseModel):
    idempotency_key: Optional[str] = None
    options: Optional[Any] = None
