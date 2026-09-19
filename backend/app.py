"""Thin HTTP wrapper around catalog.ingest, pipeline.ask, and the session store."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import Request

from backend import audit, catalog, guard, llm, narrate, pipeline
from backend.models import AskResponse
from backend.pipeline import Session
from backend.session import store

# uvicorn configures only its own loggers, so without this the plumb loggers
# propagate to a root logger with no handler and every warning the pipeline
# raises — rate limits, discarded narrations, guard rejections — is silently
# dropped. Those lines are the whole point of an auditable tool.
logging.basicConfig(
    level=os.environ.get("PLUMB_LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s:%(name)s:%(message)s",
)

log = logging.getLogger("plumb.app")

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
ALLOWED_SUFFIXES = {".csv", ".tsv", ".xlsx"}


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AskBody(BaseModel):
    session_id: str
    question: str = Field(min_length=1)


class SettleBody(BaseModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Name the provider and model on boot.

    `GROQ_API_KEY is not set` used to be discoverable only from a failed
    question, which read as the app being confused about the data. Saying it
    at startup makes a missing key a boot-time fact instead of a mid-demo
    mystery.
    """
    provider = _provider()
    log.info("plumb starting: provider=%s model=%s", provider, _model())
    if provider == "groq" and not os.environ.get("GROQ_API_KEY"):
        log.warning(
            "GROQ_API_KEY is not set — every question will fail. "
            "Put it in .env (see .env.example) or set PLUMB_PROVIDER=ollama."
        )
    yield


app = FastAPI(title="plumb", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require(session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise AppError("session_not_found", f"no session {session_id}", 404)
    return session


def _save_upload(upload: UploadFile) -> str:
    name = upload.filename or "upload.csv"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError(
            "unsupported_type",
            f"{name} is not a CSV, TSV, or XLSX file",
            400,
        )
    folder = Path(tempfile.mkdtemp(prefix="plumb_"))
    dest = folder / Path(name).name
    with dest.open("wb") as fh:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    return str(dest)


def _provider() -> str:
    return os.environ.get("PLUMB_PROVIDER", "groq").strip().lower() or "groq"


def _model() -> str:
    if _provider() == "ollama":
        return os.environ.get("PLUMB_MODEL", llm.OLLAMA_MODEL)
    return os.environ.get("PLUMB_MODEL", llm.GROQ_MODEL)


def _log_turn(session_id: str, question: str, response: AskResponse) -> None:
    row_count = len(response.rows) if response.rows is not None else 0
    verified = False
    if response.route == "answer" and response.rows is not None:
        verified = narrate.verify_narration(response.narration or "", response.rows)
    audit.append(
        session_id,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "question": question,
            "route": response.route,
            "sql": response.sql,
            "row_count": row_count,
            "elapsed_ms": response.elapsed_ms,
            "model": _model(),
            "provider": _provider(),
            "guard_errors": [],
            # Distinct from guard_errors on purpose: a rate limit says nothing
            # about the SQL or the data, so it must not read as one.
            "error_code": response.error_code,
            "tables_sent": response.tables_sent,
            "definitions_applied": dict(response.definitions_applied),
            "narration_verified": verified,
        },
    )


@app.exception_handler(AppError)
async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
) -> dict[str, object]:
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    if not uploads:
        raise AppError("no_file", "attach a CSV, TSV, or XLSX file", 400)

    saved: list[str] = []
    try:
        for item in uploads:
            saved.append(_save_upload(item))
        try:
            con, tables = catalog.ingest_many(saved, "upload")
        except ValueError as e:
            raise AppError("ingest_failed", str(e), 400) from e
        except Exception as e:
            raise AppError("ingest_failed", f"could not read the spreadsheet: {e}", 400) from e
        guard.safe_connection(con)
        session_id = store.create(Session(con=con, tables=tables))
        return {"session_id": session_id, "tables": [t.model_dump() for t in tables]}
    finally:
        for path in saved:
            parent = Path(path).parent
            try:
                shutil.rmtree(parent)
            except OSError as e:
                log.warning("could not remove temp upload dir %s: %s", parent, e)


@app.post("/api/ask")
def ask(body: AskBody) -> AskResponse:
    session = _require(body.session_id)
    question = body.question.strip()
    lock = store.lock_for(body.session_id)
    try:
        if lock is None:
            raise AppError("session_not_found", f"no session {body.session_id}", 404)
        with lock:
            response = pipeline.ask(question, session)
    except AppError:
        raise
    except Exception as e:
        raise AppError("ask_failed", str(e), 502) from e
    _log_turn(body.session_id, question, response)
    return response


@app.post("/api/session/{session_id}/settle")
def settle(session_id: str, body: SettleBody) -> dict[str, dict[str, str]]:
    session = _require(session_id)
    lock = store.lock_for(session_id)
    if lock is None:
        raise AppError("session_not_found", f"no session {session_id}", 404)
    with lock:
        session.settle(body.term, body.definition)
        snapshot = dict(session.definitions)
    return {"definitions": snapshot}


@app.get("/api/session/{session_id}/schema")
def schema(session_id: str) -> list[dict[str, object]]:
    session = _require(session_id)
    return [t.model_dump() for t in session.tables]


@app.get("/api/session/{session_id}/audit")
def session_audit(session_id: str) -> list[dict[str, object]]:
    _require(session_id)
    return audit.read(session_id)


if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = DIST / "index.html"
        if not index.is_file():
            raise AppError("frontend_missing", "frontend is not built", 404)
        return FileResponse(index)
