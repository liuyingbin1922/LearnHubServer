import os
import uuid
from typing import Dict

from shared.config import get_settings


def ensure_storage_root() -> None:
    settings = get_settings()
    os.makedirs(settings.storage_root, exist_ok=True)


def build_object_key(user_id: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1]
    return f"user/{user_id}/{uuid.uuid4().hex}{ext}"


def get_local_path(object_key: str) -> str:
    settings = get_settings()
    return os.path.join(settings.storage_root, object_key)


def get_public_url(object_key: str) -> str:
    settings = get_settings()
    return f"{settings.public_base_url}/{object_key}"


def build_presign_response(user_id: str, filename: str) -> Dict[str, str]:
    object_key = build_object_key(user_id, filename)
    upload_url = "/api/v1/uploads/direct"
    return {
        "upload_url": upload_url,
        "headers": {},
        "object_key": object_key,
        "public_url": get_public_url(object_key),
    }
