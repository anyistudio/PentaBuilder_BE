from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import (
    AIRun,
    CachedContextResult,
    DataVersion,
    LeaderboardEntry,
    SessionRecord,
    User,
)


class UsersRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> User:
        user = User(**kwargs)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_auth_subject(self, auth_provider: str, auth_subject: str) -> User | None:
        stmt = sa.select(User).where(
            User.auth_provider == auth_provider,
            User.auth_subject == auth_subject,
        )
        return self.session.scalar(stmt)


class DataVersionsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> DataVersion:
        data_version = DataVersion(**kwargs)
        self.session.add(data_version)
        self.session.commit()
        self.session.refresh(data_version)
        return data_version

    def list(self, *, active_only: bool = False) -> list[DataVersion]:
        stmt = sa.select(DataVersion).order_by(DataVersion.created_at.desc())
        if active_only:
            stmt = stmt.where(DataVersion.is_active.is_(True))
        return list(self.session.scalars(stmt))

    def get_active(self) -> DataVersion | None:
        stmt = sa.select(DataVersion).where(DataVersion.is_active.is_(True))
        return self.session.scalar(stmt)

    def get_by_data_version(self, data_version: str) -> DataVersion | None:
        stmt = sa.select(DataVersion).where(DataVersion.data_version == data_version)
        return self.session.scalar(stmt)

    def activate(self, data_version: str) -> DataVersion:
        self.session.execute(sa.update(DataVersion).values(is_active=False))
        record = self.get_by_data_version(data_version)
        if record is None:
            raise LookupError(f"Unknown data_version {data_version!r}")
        record.is_active = True
        record.activated_at = datetime.now(tz=timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record


class SessionsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> SessionRecord:
        record = SessionRecord(**kwargs)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get(self, session_id: UUID) -> SessionRecord | None:
        return self.session.get(SessionRecord, session_id)

    def list_for_user(self, user_id: UUID) -> list[SessionRecord]:
        stmt = (
            sa.select(SessionRecord)
            .where(SessionRecord.user_id == user_id)
            .order_by(SessionRecord.updated_at.desc())
        )
        return list(self.session.scalars(stmt))


class AIRunsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> AIRun:
        run = AIRun(**kwargs)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def get(self, run_id: UUID) -> AIRun | None:
        return self.session.get(AIRun, run_id)


class CacheRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> CachedContextResult:
        cache_entry = CachedContextResult(**kwargs)
        self.session.add(cache_entry)
        self.session.commit()
        self.session.refresh(cache_entry)
        return cache_entry

    def get_by_response_variant_hash(
        self,
        *,
        run_type: str,
        response_variant_hash: str,
    ) -> CachedContextResult | None:
        stmt = sa.select(CachedContextResult).where(
            CachedContextResult.run_type == run_type,
            CachedContextResult.response_variant_hash == response_variant_hash,
        )
        return self.session.scalar(stmt)


class LeaderboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **kwargs: Any) -> LeaderboardEntry:
        entry = LeaderboardEntry(**kwargs)
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def get_by_scope(
        self,
        *,
        game: str,
        data_version: str,
        own_champion_slug: str,
        enemy_champion_slug: str | None,
    ) -> LeaderboardEntry | None:
        stmt = sa.select(LeaderboardEntry).where(
            LeaderboardEntry.game == game,
            LeaderboardEntry.data_version == data_version,
            LeaderboardEntry.own_champion_slug == own_champion_slug,
            LeaderboardEntry.enemy_champion_slug.is_(enemy_champion_slug)
            if enemy_champion_slug is None
            else LeaderboardEntry.enemy_champion_slug == enemy_champion_slug,
        )
        return self.session.scalar(stmt)
