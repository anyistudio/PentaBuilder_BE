# Deployment Guide

## Railway Files

The repo includes:

- `Procfile`
- `railway.toml`
- `nixpacks.toml`
- `scripts/railway_start.sh`

`scripts/railway_start.sh` does:

1. `uv run alembic upgrade head`
2. `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Required services

You need:

1. Railway app for this API
2. PostgreSQL
3. S3-compatible object storage
4. Clerk project
5. Google API key for Gemini

## Required env vars

Start from `.env.prod.example`.

Minimum production variables:

- `APP_ENV=production`
- `DATABASE_URL`
- `S3_ENDPOINT`
- `S3_BUCKET`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_REGION`
- `JWT_SIGNING_KEY`
- `CLERK_SECRET_KEY`
- `CLERK_JWKS_URL`
- `CLERK_ISSUER`
- `CORS_ALLOWED_ORIGINS`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `GOOGLE_API_KEY`
- `PRIMARY_REASONING_PROVIDER`
- `PRIMARY_REASONING_MODEL`
- `FAST_REASONING_PROVIDER`
- `FAST_REASONING_MODEL`
- `CALIBRATION_PROVIDER`
- `CALIBRATION_MODEL`
- `GAME_DATA_SOURCE=s3`
- `GAME_DATA_S3_ROOT`

## Deploy steps

1. Create the Railway project.
2. Connect this repo.
3. Attach PostgreSQL.
4. Set all production env vars.
   - Example: `CORS_ALLOWED_ORIGINS=https://your-frontend.up.railway.app`
5. Deploy and wait for `healthcheckPath=/healthz` to pass.
6. Trigger admin jobs:
   - `POST /api/v1/admin/jobs/precompute-baselines`
   - `POST /api/v1/admin/jobs/generate-calibrations`
7. Verify:
   - `GET /healthz`
   - `GET /api/v1/catalog/versions/current`
   - auth exchange
   - one `POST /api/v1/ai/runs`

## Post-deploy sequence

1. Trigger baseline precompute for `lol`
2. Trigger baseline precompute for `wild_rift`
3. Trigger calibration generation
4. Trigger benchmark run on the default dataset
