import base64
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from services.api.security.jwt_verify import TokenVerificationError, verify_bearer_token
from shared.config import get_settings


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


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    monkeypatch.setenv("LEARNHUB_BETTER_AUTH_JWKS_URL", "http://jwks.local")
    monkeypatch.setenv("LEARNHUB_BETTER_AUTH_ISSUER", "https://issuer")
    monkeypatch.delenv("LEARNHUB_BETTER_AUTH_AUDIENCE", raising=False)
    get_settings.cache_clear()
    from services.api.security import jwks_client

    jwks_client._jwks_client = None
    yield
    get_settings.cache_clear()
    jwks_client._jwks_client = None


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def test_verify_bearer_token_success(monkeypatch, rsa_keys):
    private_key, public_key = rsa_keys
    kid = "kid-1"
    jwks = _build_jwks(public_key, kid)
    _mock_jwks(monkeypatch, jwks)

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": "https://issuer",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    claims = verify_bearer_token(token)
    assert claims["sub"] == "user-1"


def test_verify_bearer_token_invalid_issuer(monkeypatch, rsa_keys):
    private_key, public_key = rsa_keys
    kid = "kid-2"
    jwks = _build_jwks(public_key, kid)
    _mock_jwks(monkeypatch, jwks)

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": "https://other",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_verify_bearer_token_expired(monkeypatch, rsa_keys):
    private_key, public_key = rsa_keys
    kid = "kid-3"
    jwks = _build_jwks(public_key, kid)
    _mock_jwks(monkeypatch, jwks)

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": "https://issuer",
            "exp": int(time.time()) - 10,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)


def test_verify_bearer_token_invalid_audience(monkeypatch, rsa_keys):
    monkeypatch.setenv("LEARNHUB_BETTER_AUTH_AUDIENCE", "expected")
    get_settings.cache_clear()
    private_key, public_key = rsa_keys
    kid = "kid-4"
    jwks = _build_jwks(public_key, kid)
    _mock_jwks(monkeypatch, jwks)

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": "https://issuer",
            "aud": "other",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    with pytest.raises(TokenVerificationError):
        verify_bearer_token(token)
