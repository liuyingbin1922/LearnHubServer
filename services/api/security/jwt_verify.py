import json

import jwt

from services.api.security.jwks_client import get_jwks_client
from shared.config import get_settings


class TokenVerificationError(Exception):
    pass


def verify_bearer_token(token: str) -> dict:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise TokenVerificationError("missing kid")
        jwk = get_jwks_client().get_signing_key(kid)
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        options = {"verify_aud": bool(settings.better_auth_audience)}
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.better_auth_issuer,
            audience=settings.better_auth_audience or None,
            options=options,
        )
        return claims
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise TokenVerificationError("invalid token") from exc
