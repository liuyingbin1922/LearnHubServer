# LearnHubServer

FastAPI + PostgreSQL + Redis + Celery worker skeleton for LearnHub.

## Quick start

```bash
cd infra
docker-compose up --build
```

Health check:

```bash
curl http://localhost:8000/healthz
```

## Migrations

```bash
alembic -c alembic.ini upgrade head
```

## Env vars

All env vars use `LEARNHUB_` prefix.

- `LEARNHUB_DATABASE_URL` (default `postgresql+psycopg2://postgres:postgres@db:5432/learnhub`)
- `LEARNHUB_REDIS_URL` (default `redis://redis:6379/0`)
- `LEARNHUB_JWT_SECRET`
- `LEARNHUB_PUBLIC_BASE_URL` (default `http://localhost:8000/media`)
- `LEARNHUB_BETTER_AUTH_JWKS_URL`
- `LEARNHUB_BETTER_AUTH_ISSUER`
- `LEARNHUB_BETTER_AUTH_AUDIENCE` (optional)
- `LEARNHUB_BETTER_AUTH_JWKS_CACHE_TTL_SECONDS`
- `LEARNHUB_AUTH_DEV_BYPASS` (`true`/`false`)
- `LEARNHUB_AUTH_DEV_USER_SUB` (dev bypass sub)
- `LEARNHUB_AUTH_PROVIDER_NAME` (default `better_auth`)

## Authentication contract

The API trusts Better Auth-issued JWTs. Clients must acquire a JWT from Better Auth (e.g. Next.js `/api/auth`) and send it as `Authorization: Bearer <token>` to FastAPI. The API verifies the token against the configured JWKS endpoint.

## E2E

Use `scripts/e2e.http` with VSCode REST client or copy commands.

## Dev seed

```bash
python scripts/dev_seed.py
```
