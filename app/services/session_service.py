from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.schemas.session import SessionSummarySchema
from app.core.errors import ApiError
from app.db.models import AIRun, SessionRecord, User
from app.domain.match_context import MatchContext, SessionEvent
from app.services.storage_service import StorageService


class SessionService:
    def __init__(self, storage_service: StorageService) -> None:
        self.storage_service = storage_service

    def create_session(
        self,
        session: Session,
        *,
        user: User,
        client_session_id: str | None,
        initial_context: MatchContext,
    ) -> SessionRecord:
        transcript_payload = self._empty_transcript(
            client_session_id=client_session_id,
            initial_context=initial_context.model_dump(mode="json"),
        )
        session_record = SessionRecord(
            user_id=user.id,
            client_session_id=client_session_id,
            game=initial_context.game.value,
            data_version=initial_context.data_version,
            title=self._build_title(initial_context),
            last_context_snapshot=initial_context.model_dump(mode="json"),
            transcript_object_key=f"sessions/{user.id}/{datetime.now(tz=timezone.utc).timestamp():.0f}.json",
            event_count=0,
        )
        session.add(session_record)
        session.commit()
        session.refresh(session_record)

        transcript_payload["session_id"] = str(session_record.id)
        transcript_payload["transcript_version"] = 1
        transcript_payload["created_at"] = datetime.now(tz=timezone.utc).isoformat()
        session_record.transcript_object_key = (
            f"sessions/{user.id}/{session_record.id}/transcript.json"
        )
        self.storage_service.write_json(session_record.transcript_object_key, transcript_payload)
        session.add(session_record)
        session.commit()
        session.refresh(session_record)
        return session_record

    def list_sessions(
        self,
        session: Session,
        *,
        user: User,
        limit: int = 20,
    ) -> list[SessionRecord]:
        stmt = (
            sa.select(SessionRecord)
            .where(SessionRecord.user_id == user.id)
            .order_by(SessionRecord.updated_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt))

    def get_session(self, session: Session, *, user: User, session_id: UUID) -> SessionRecord:
        record = session.get(SessionRecord, session_id)
        if record is None:
            raise ApiError("Session not found.", details={"code": "session_not_found"})
        if record.user_id != user.id:
            raise ApiError("Unauthorized session.", details={"code": "unauthorized_session"})
        return record

    def get_session_detail(
        self, session: Session, *, user: User, session_id: UUID
    ) -> tuple[SessionRecord, dict]:
        record = self.get_session(session, user=user, session_id=session_id)
        transcript = self.storage_service.read_json_object(record.transcript_object_key)
        return record, transcript

    def delete_session(self, session: Session, *, user: User, session_id: UUID) -> None:
        record = self.get_session(session, user=user, session_id=session_id)
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

    def claim_session(
        self,
        session: Session,
        *,
        user: User,
        session_id: UUID,
        client_session_id: str,
        events: list[SessionEvent],
    ) -> dict:
        record = self.get_session(session, user=user, session_id=session_id)
        transcript = self.storage_service.read_json_object(record.transcript_object_key)
        transcript["client_session_id"] = client_session_id
        transcript.setdefault("events", [])
        transcript["events"].extend([event.model_dump(mode="json") for event in events])
        transcript["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        record.client_session_id = client_session_id
        record.event_count = len(transcript["events"])
        self.storage_service.write_json(record.transcript_object_key, transcript)
        session.add(record)
        session.commit()
        session.refresh(record)
        return transcript

    def append_run_event(
        self,
        session: Session,
        *,
        session_record: SessionRecord,
        run_id: UUID,
        run_type: str,
        summary: str,
        result: dict[str, Any],
    ) -> None:
        transcript = self.storage_service.read_json_object(session_record.transcript_object_key)
        transcript.setdefault("events", []).append(
            {
                "type": "ai_run",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "payload": {
                    "run_id": str(run_id),
                    "run_type": run_type,
                    "summary": summary,
                    "result": result,
                },
            }
        )
        transcript["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        session_record.event_count = len(transcript["events"])
        self.storage_service.write_json(session_record.transcript_object_key, transcript)
        session.add(session_record)
        session.commit()

    def to_summary_schema(self, record: SessionRecord) -> SessionSummarySchema:
        return SessionSummarySchema(
            id=str(record.id),
            title=record.title,
            game=record.game,
            data_version=record.data_version,
            event_count=record.event_count,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
            last_context_snapshot=record.last_context_snapshot,
        )

    def _empty_transcript(
        self,
        *,
        client_session_id: str | None,
        initial_context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "transcript_version": 1,
            "client_session_id": client_session_id,
            "initial_context": initial_context,
            "events": [],
        }

    def _build_title(self, initial_context: MatchContext) -> str:
        if initial_context.enemy_team:
            return (
                f"{initial_context.own_champion_slug} "
                f"vs {initial_context.enemy_team[0].champion_slug}"
            )
        return initial_context.own_champion_slug
