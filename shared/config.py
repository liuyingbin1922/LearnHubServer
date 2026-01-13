from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    database_url: str = "postgresql+psycopg2://postgres:postgres@db:5432/learnhub"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 3600
    refresh_token_expire_seconds: int = 60 * 60 * 24 * 30
    sms_code_expire_seconds: int = 300
    sms_ip_rate_limit_per_hour: int = 20
    sms_phone_rate_limit_seconds: int = 60
    wechat_app_id: str = "mock-app-id"
    wechat_app_secret: str = "mock-app-secret"
    wechat_mock: bool = True
    frontend_auth_callback_url: str = "http://localhost:3000/auth/callback"
    better_auth_jwks_url: str = "http://localhost:3000/api/auth/jwks"
    better_auth_issuer: str = "http://localhost:3000"
    better_auth_audience: str | None = None
    better_auth_jwks_cache_ttl_seconds: int = 21600
    auth_dev_bypass: bool = False
    auth_dev_user_sub: str = "dev-user"
    auth_provider_name: str = "better_auth"
    storage_root: str = "/data/storage"
    public_base_url: str = "http://localhost:8000/media"

    class Config:
        env_prefix = "LEARNHUB_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
