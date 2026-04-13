import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
import sqlalchemy as sa
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.api.schemas.auth import UserSchema
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import (
    AdminJobRun,
    AIRun,
    BaselineBuild,
    BenchmarkResult,
    CachedContextResult,
    SessionRecord,
    User,
)
from app.repositories.core import UsersRepository
from app.services.leaderboard_service import LeaderboardService
from app.services.storage_service import StorageService


@dataclass
class AuthenticatedPrincipal:
    user: User
    access_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int | None = None


class AuthService:
    def __init__(
        self,
        settings: Settings,
        *,
        storage_service: StorageService,
        leaderboard_service: LeaderboardService,
    ) -> None:
        self.settings = settings
        self.storage_service = storage_service
        self.leaderboard_service = leaderboard_service
        self._jwks_client: PyJWKClient | None = None

    def exchange_token(
        self,
        session: Session,
        *,
        provider: str,
        provider_token: str,
    ) -> AuthenticatedPrincipal:
        if provider != "clerk":
            raise ApiError("Unsupported auth provider.", details={"code": "invalid_provider"})

        claims = self.verify_clerk_token(provider_token)
        user = self._upsert_user_from_claims(session, claims)
        access_token = self.issue_access_token(user.id)
        return AuthenticatedPrincipal(
            user=user,
            access_token=access_token,
            expires_in=self.settings.access_token_ttl_seconds,
        )

    def verify_clerk_token(self, token: str) -> dict[str, Any]:
        if (
            token.startswith("dev-clerk:")
            and self.settings.dev_auth_enabled
            and self.settings.is_local
        ):
            return self._parse_dev_token(token)

        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            kwargs: dict[str, Any] = {
                "algorithms": ["RS256"],
                "issuer": self.settings.clerk_issuer,
                "options": {"verify_aud": bool(self.settings.clerk_audience)},
            }
            if self.settings.clerk_audience:
                kwargs["audience"] = self.settings.clerk_audience
            return jwt.decode(token, signing_key.key, **kwargs)
        except Exception as exc:  # pragma: no cover - exercised in integration/manual setup
            raise ApiError(
                "Invalid Clerk token.",
                details={"code": "invalid_provider_token", "reason": str(exc)},
            ) from exc

    def issue_access_token(self, user_id: UUID) -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": str(user_id),
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(seconds=self.settings.access_token_ttl_seconds)).timestamp()
            ),
        }
        return jwt.encode(
            payload,
            self.settings.jwt_signing_key.get_secret_value(),
            algorithm="HS256",
        )

    def authenticate_access_token(self, session: Session, token: str) -> User | None:
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_signing_key.get_secret_value(),
                algorithms=["HS256"],
            )
        except Exception as exc:
            raise ApiError(
                "Invalid access token.", details={"code": "invalid_access_token"}
            ) from exc

        if claims.get("type") != "access":
            raise ApiError("Invalid access token.", details={"code": "invalid_access_token"})

        try:
            user_id = UUID(claims["sub"])
        except Exception as exc:
            raise ApiError(
                "Invalid access token.", details={"code": "invalid_access_token"}
            ) from exc

        user = session.get(User, user_id)
        if user is None:
            raise ApiError("User not found.", details={"code": "invalid_access_token"})
        return user

    def is_valid_admin_credentials(self, username: str, password: str) -> bool:
        return secrets.compare_digest(
            username, self.settings.admin_username
        ) and secrets.compare_digest(
            password,
            self.settings.admin_password.get_secret_value(),
        )

    def update_preferences(
        self,
        session: Session,
        *,
        user: User,
        username: str | None,
        preferred_language: str | None,
        preferred_terminology_style: str | None,
    ) -> User:
        if username is not None:
            user.username = username
        if preferred_language is not None:
            user.preferred_language = preferred_language
        if preferred_terminology_style is not None:
            user.preferred_terminology_style = preferred_terminology_style
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    def delete_user(self, session: Session, *, user: User) -> None:
        session_records = list(
            session.scalars(
                sa.select(SessionRecord)
                .where(SessionRecord.user_id == user.id)
                .order_by(SessionRecord.created_at)
            )
        )
        for record in session_records:
            run_keys = list(
                session.scalars(
                    sa.select(AIRun.artifact_object_key).where(
                        AIRun.session_id == record.id,
                        AIRun.artifact_object_key.is_not(None),
                    )
                )
            )
            for object_key in run_keys:
                if object_key:
                    self.storage_service.delete_object(object_key)
            self.storage_service.delete_object(record.transcript_object_key)
            session.execute(sa.delete(AIRun).where(AIRun.session_id == record.id))
            session.delete(record)
            session.commit()

        remaining_run_ids = list(
            session.scalars(
                sa.select(AIRun.id).where(AIRun.user_id == user.id).order_by(AIRun.created_at)
            )
        )
        if remaining_run_ids:
            run_artifacts = list(
                session.scalars(
                    sa.select(AIRun.artifact_object_key).where(
                        AIRun.id.in_(remaining_run_ids),
                        AIRun.artifact_object_key.is_not(None),
                    )
                )
            )
            for object_key in run_artifacts:
                if object_key:
                    self.storage_service.delete_object(object_key)
            session.execute(
                sa.delete(CachedContextResult).where(
                    CachedContextResult.source_run_id.in_(remaining_run_ids)
                )
            )
            session.execute(
                sa.update(BaselineBuild)
                .where(BaselineBuild.source_run_id.in_(remaining_run_ids))
                .values(source_run_id=None)
            )
            session.execute(
                sa.delete(BenchmarkResult).where(BenchmarkResult.ai_run_id.in_(remaining_run_ids))
            )
            session.execute(sa.delete(AIRun).where(AIRun.id.in_(remaining_run_ids)))

        session.execute(
            sa.update(AdminJobRun)
            .where(AdminJobRun.requested_by_user_id == user.id)
            .values(requested_by_user_id=None)
        )
        session.flush()
        self.leaderboard_service.recompute_for_user(session, user_id=user.id)
        session.delete(user)
        session.commit()

    def to_user_schema(self, user: User) -> UserSchema:
        return UserSchema(
            id=str(user.id),
            auth_provider=user.auth_provider,
            email=user.email,
            email_verified=user.email_verified,
            display_name=user.display_name,
            username=user.username,
            icon_url=user.icon_url,
            preferred_language=user.preferred_language,
            preferred_terminology_style=user.preferred_terminology_style,
        )

    def _upsert_user_from_claims(self, session: Session, claims: dict[str, Any]) -> User:
        auth_subject = str(claims.get("sub"))
        if not auth_subject:
            raise ApiError("Invalid Clerk token.", details={"code": "invalid_provider_token"})

        repository = UsersRepository(session)
        user = repository.get_by_auth_subject("clerk", auth_subject)
        if user is None:
            user = User(auth_provider="clerk", auth_subject=auth_subject)

        user.email = claims.get("email") or claims.get("email_address")
        user.email_verified = bool(
            claims.get("email_verified")
            or claims.get("verified")
            or (claims.get("email_addresses") and claims.get("primary_email_address_id"))
        )
        user.display_name = self._build_display_name(claims)
        user.icon_url = claims.get("picture") or claims.get("image_url")
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    def _build_display_name(self, claims: dict[str, Any]) -> str | None:
        if claims.get("name"):
            return str(claims["name"])
        first = claims.get("given_name") or claims.get("first_name")
        last = claims.get("family_name") or claims.get("last_name")
        display_name = " ".join(part for part in (first, last) if part)
        return display_name or None

    def _parse_dev_token(self, token: str) -> dict[str, Any]:
        parts = token.split(":")
        if len(parts) < 2:
            raise ApiError("Invalid Clerk token.", details={"code": "invalid_provider_token"})
        subject = parts[1]
        email = parts[2] if len(parts) > 2 and parts[2] else f"{subject}@local.dev"
        display_name = parts[3] if len(parts) > 3 and parts[3] else subject
        return {
            "sub": subject,
            "email": email,
            "email_verified": True,
            "name": display_name,
            "iss": self.settings.clerk_issuer,
        }

    @property
    def jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.settings.clerk_jwks_url)
        return self._jwks_client
