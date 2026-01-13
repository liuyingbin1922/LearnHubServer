import base64
import importlib
import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.db import Base
from shared.models import AuthIdentity, User


def _b64url_uint(val: int) -> str:
    raw = val.to_bytes((val.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def _build_jwks(public_key, kid: str) -> dict:
    numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


def _mock_jwks(monkeypatch, jwks: dict):
    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_get(url, timeout):
        return DummyResponse(jwks)

    monkeypatch.setattr("httpx.get", fake_get)


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_auto_provisioning_creates_user(monkeypatch):
    test_db_url = os.getenv("TEST_DATABASE_URL")
    monkeypatch.setenv("LEARNHUB_DATABASE_URL", test_db_url)
    monkeypatch.setenv("LEARNHUB_BETTER_AUTH_JWKS_URL", "http://jwks.local")
    monkeypatch.setenv("LEARNHUB_BETTER_AUTH_ISSUER", "https://issuer")
    monkeypatch.setenv("LEARNHUB_AUTH_DEV_BYPASS", "false")
    get_settings.cache_clear()

    from services.api.security import jwks_client

    jwks_client._jwks_client = None

    engine = create_engine(test_db_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    kid = "kid-provision"
    jwks = _build_jwks(public_key, kid)
    _mock_jwks(monkeypatch, jwks)

    token = jwt.encode(
        {
            "sub": "user-sub-1",
            "iss": "https://issuer",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "name": "User One",
            "picture": "https://example.com/avatar.png",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    import services.api.main as main

    importlib.reload(main)
    client = TestClient(main.app)
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    session = Session(engine)
    identity = session.query(AuthIdentity).filter(AuthIdentity.provider_uid == "user-sub-1").first()
    assert identity is not None
    user = session.query(User).filter(User.id == identity.user_id).first()
    assert user.nickname == "User One"
    session.close()
