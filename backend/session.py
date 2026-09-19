"""In-memory store of engine Session objects, keyed by uuid."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from backend.pipeline import Session

IDLE_SECONDS = 2 * 60 * 60


@dataclass
class _Entry:
    session: Session
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """Thread-safe uuid-keyed store. Idle sessions are closed after 2 hours."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _Entry] = {}

    def create(self, session: Session) -> str:
        session_id = str(uuid.uuid4())
        with self._lock:
            self._evict_unlocked(time.time())
            self._sessions[session_id] = _Entry(session=session)
        return session_id

    def get(self, session_id: str) -> Session | None:
        now = time.time()
        with self._lock:
            self._evict_unlocked(now)
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            entry.last_used = now
            return entry.session

    def lock_for(self, session_id: str) -> threading.Lock | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            return None if entry is None else entry.lock

    def _evict_unlocked(self, now: float) -> None:
        expired = [
            sid
            for sid, entry in self._sessions.items()
            if now - entry.last_used > IDLE_SECONDS
        ]
        for sid in expired:
            entry = self._sessions.pop(sid)
            try:
                entry.session.con.close()
            except Exception as e:
                raise RuntimeError(
                    f"failed to close DuckDB connection for session {sid}"
                ) from e


store = SessionStore()
