from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from services.api.security.jwt_verify import TokenVerificationError, verify_bearer_token
from shared.config import get_settings


class AuthMiddleware:
    def __init__(self, app: Callable):
        self.app = app
        self.settings = get_settings()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if self.settings.auth_dev_bypass:
            request.state.external_sub = self.settings.auth_dev_user_sub
            request.state.claims = {"sub": self.settings.auth_dev_user_sub}
            await self.app(scope, receive, send)
            return
        auth_header = request.headers.get("authorization")
        request_id = request.headers.get("x-request-id") or ""
        if auth_header:
            if not auth_header.lower().startswith("bearer "):
                response = JSONResponse(
                    {"code": 401, "message": "invalid authorization header", "data": None, "request_id": request_id},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
            token = auth_header.split(" ", 1)[1]
            try:
                claims = verify_bearer_token(token)
            except TokenVerificationError:
                response = JSONResponse(
                    {"code": 401, "message": "invalid token", "data": None, "request_id": request_id},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
            request.state.external_sub = claims.get("sub")
            request.state.claims = claims
        await self.app(scope, receive, send)
