import time
from typing import Any, Dict

import httpx

from shared.config import get_settings


class JWKSClient:
    def __init__(self, jwks_url: str, cache_ttl: int) -> None:
        self.jwks_url = jwks_url
        self.cache_ttl = cache_ttl
        self._keys: Dict[str, Dict[str, Any]] = {}
        self._expires_at = 0.0

    def _refresh(self) -> None:
        response = httpx.get(self.jwks_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        keys = {key["kid"]: key for key in payload.get("keys", []) if "kid" in key}
        self._keys = keys
        self._expires_at = time.time() + self.cache_ttl

    def get_signing_key(self, kid: str) -> Dict[str, Any]:
        if time.time() >= self._expires_at:
            self._refresh()
        key = self._keys.get(kid)
        if not key:
            self._refresh()
            key = self._keys.get(kid)
        if not key:
            raise KeyError(f"signing key not found for kid={kid}")
        return key


_jwks_client: JWKSClient | None = None


def get_jwks_client() -> JWKSClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        _jwks_client = JWKSClient(settings.better_auth_jwks_url, settings.better_auth_jwks_cache_ttl_seconds)
    return _jwks_client
