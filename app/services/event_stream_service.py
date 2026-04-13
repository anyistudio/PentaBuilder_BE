import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

TERMINAL_EVENTS = {"run_completed", "run_failed"}


@dataclass
class StreamState:
    events: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False


class EventStreamService:
    def __init__(self) -> None:
        self._streams: dict[str, StreamState] = {}
        self._lock = threading.Lock()

    def init_run(self, run_id: str) -> None:
        with self._lock:
            self._streams.setdefault(run_id, StreamState())

    def publish(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            state = self._streams.setdefault(run_id, StreamState())
            state.events.append({"event": event, "data": data})
            if event in TERMINAL_EVENTS:
                state.closed = True

    def stream(self, run_id: str, *, poll_interval: float = 0.05) -> Iterator[bytes]:
        index = 0
        while True:
            with self._lock:
                state = self._streams.get(run_id, StreamState())
                pending = state.events[index:]
                closed = state.closed
            for event_payload in pending:
                index += 1
                yield self._format_event(event_payload["event"], event_payload["data"])
            if closed and index >= len(state.events):
                break
            time.sleep(poll_interval)

    def _format_event(self, event: str, data: dict[str, Any]) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
