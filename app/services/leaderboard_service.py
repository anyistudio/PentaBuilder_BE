from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import AIRun, LeaderboardEntry, User


class LeaderboardService:
    def update_from_run(
        self,
        session: Session,
        *,
        run: AIRun,
        result: dict[str, Any],
        username_snapshot: str | None,
    ) -> None:
        if run.run_type != "evaluate_build" or result.get("score") is None:
            return
        enemy_slug = None
        if run.enemy_comp_key and run.enemy_comp_key != "_none":
            enemy_parts = run.enemy_comp_key.split("|")
            if len(enemy_parts) > 1:
                return
            enemy_slug = enemy_parts[0]

        stmt = sa.select(LeaderboardEntry).where(
            LeaderboardEntry.game == run.game,
            LeaderboardEntry.data_version == run.data_version,
            LeaderboardEntry.own_champion_slug == run.own_champion_slug,
            LeaderboardEntry.enemy_champion_slug.is_(enemy_slug)
            if enemy_slug is None
            else LeaderboardEntry.enemy_champion_slug == enemy_slug,
        )
        entry = session.scalar(stmt)
        score = int(result["score"])
        if username_snapshot is None and run.user_id is not None:
            owner = session.get(User, run.user_id)
            username_snapshot = owner.username if owner is not None else None
        if entry is None:
            entry = LeaderboardEntry(
                game=run.game,
                data_version=run.data_version,
                own_champion_slug=run.own_champion_slug or "",
                enemy_champion_slug=enemy_slug,
                top_run_id=run.id,
                top_session_id=run.session_id,
                top_user_id=run.user_id,
                top_username_snapshot=username_snapshot,
                top_score=score,
                updated_at=datetime.now(tz=timezone.utc),
            )
            session.add(entry)
        elif score >= entry.top_score:
            entry.top_run_id = run.id
            entry.top_session_id = run.session_id
            entry.top_user_id = run.user_id
            entry.top_username_snapshot = username_snapshot
            entry.top_score = score
            entry.updated_at = datetime.now(tz=timezone.utc)
            session.add(entry)
        session.commit()

    def list_entries(
        self,
        session: Session,
        *,
        game: str,
        data_version: str,
        own_champion_slug: str | None,
        enemy_champion_slug: str | None,
        limit: int,
        offset: int,
    ) -> list[LeaderboardEntry]:
        stmt = (
            sa.select(LeaderboardEntry)
            .where(
                LeaderboardEntry.game == game,
                LeaderboardEntry.data_version == data_version,
            )
            .order_by(LeaderboardEntry.top_score.desc(), LeaderboardEntry.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if own_champion_slug:
            stmt = stmt.where(LeaderboardEntry.own_champion_slug == own_champion_slug)
        if enemy_champion_slug:
            stmt = stmt.where(LeaderboardEntry.enemy_champion_slug == enemy_champion_slug)
        return list(session.scalars(stmt))

    def recompute_for_user(self, session: Session, *, user_id: UUID) -> None:
        stmt = sa.select(LeaderboardEntry).where(LeaderboardEntry.top_user_id == user_id)
        affected_entries = list(session.scalars(stmt))
        for entry in affected_entries:
            candidates_stmt = (
                sa.select(AIRun)
                .where(
                    AIRun.run_type == "evaluate_build",
                    AIRun.game == entry.game,
                    AIRun.data_version == entry.data_version,
                    AIRun.own_champion_slug == entry.own_champion_slug,
                    AIRun.score_value.is_not(None),
                )
                .order_by(AIRun.score_value.desc(), AIRun.created_at.desc())
            )
            if entry.enemy_champion_slug is None:
                candidates_stmt = candidates_stmt.where(AIRun.enemy_comp_key == "_none")
            else:
                candidates_stmt = candidates_stmt.where(
                    AIRun.enemy_comp_key == entry.enemy_champion_slug
                )
            replacement = session.scalar(candidates_stmt)
            if replacement is None:
                session.delete(entry)
            else:
                owner = session.get(User, replacement.user_id) if replacement.user_id else None
                entry.top_run_id = replacement.id
                entry.top_session_id = replacement.session_id
                entry.top_user_id = replacement.user_id
                entry.top_username_snapshot = owner.username if owner is not None else None
                entry.top_score = replacement.score_value or 0
                entry.updated_at = datetime.now(tz=timezone.utc)
                session.add(entry)
        session.commit()
