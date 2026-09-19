"""Append-only JSONL audit log, one file per session."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# The repo checkout is writable in dev and on a single container; a host that
# mounts a volume elsewhere points PLUMB_AUDIT_DIR at it. This is the only
# path plumb writes to, so it is the only one that needs to move.
AUDIT_DIR = Path(
    os.environ.get("PLUMB_AUDIT_DIR") or Path(__file__).resolve().parents[1] / "audit"
)
_LOCK = threading.Lock()


def _path(session_id: str) -> Path:
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise ValueError(f"invalid session_id for audit path: {session_id!r}")
    return AUDIT_DIR / f"{session_id}.jsonl"


def append(session_id: str, entry: dict[str, Any]) -> None:
    """Write one JSON object as a single line."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, default=str)
    with _LOCK:
        with _path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read(session_id: str) -> list[dict[str, Any]]:
    """Return every logged turn for a session, oldest first."""
    path = _path(session_id)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries
