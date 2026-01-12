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
- `LEARNHUB_FRONTEND_AUTH_CALLBACK_URL`
- `LEARNHUB_WECHAT_MOCK` (`true`/`false`)

## E2E

Use `scripts/e2e.http` with VSCode REST client or copy commands.

## Dev seed

```bash
python scripts/dev_seed.py
```
