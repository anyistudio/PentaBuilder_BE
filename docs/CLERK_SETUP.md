# Clerk Setup

## 1. Create the Clerk application

1. Create a Clerk app for the frontend domain you will use.
2. Enable the providers you want on the frontend, at least Google for v1.
3. Enable session tokens / JWT templates for backend verification.

## 2. Fill backend env vars

Set these values in backend env:

- `CLERK_SECRET_KEY`
- `CLERK_JWKS_URL`
- `CLERK_ISSUER`
- `CLERK_AUDIENCE` if your Clerk token uses `aud`

Typical values:

- `CLERK_JWKS_URL`: `https://<your-clerk-domain>/.well-known/jwks.json`
- `CLERK_ISSUER`: `https://<your-clerk-domain>`

## 3. Frontend exchange flow

1. User signs in with Clerk on the frontend.
2. Frontend gets Clerk session token.
3. Frontend calls `POST /api/v1/auth/exchange`.
4. Backend verifies the Clerk token and returns backend `access_token`.
5. Frontend uses backend `Authorization: Bearer <access_token>` for protected backend APIs.

Request example:

```json
{
  "provider": "clerk",
  "provider_token": "<clerk-session-token>"
}
```

## 4. Local development shortcut

When `APP_ENV` is local/dev/test and `DEV_AUTH_ENABLED=true`, the backend also accepts:

```text
dev-clerk:<subject>:<email>:<display_name>
```

Example:

```text
dev-clerk:user_1:test@example.com:BlueFox
```

This shortcut is only for local development and tests.

## 5. Manual verification checklist

1. Frontend signs in with Clerk successfully.
2. Backend `POST /api/v1/auth/exchange` returns `200`.
3. `GET /api/v1/me` returns the Clerk user profile with backend JWT.
4. `PATCH /api/v1/me/preferences` persists language / terminology style.
