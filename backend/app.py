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

import duckdb

from backend import audit, catalog, guard, llm, narrate, pipeline, suggestions
from backend.endpoint_guard import EndpointError
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


class ModelBody(BaseModel):
    provider: str
    model: str = Field(min_length=1)


class ProviderBody(BaseModel):
    provider: str
    model: str = Field(min_length=1)
    url: str | None = None
    key: str | None = None


class ProbeBody(BaseModel):
    url: str
    model: str = Field(min_length=1)
    key: str | None = None


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
    if provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        log.warning(
            "OPENROUTER_API_KEY is not set — every question will fail. "
            "Put it in .env (see .env.example) or pick Groq or Ollama."
        )
    yield


def _cors_origins() -> list[str]:
    """Where the dev SPA is served from. The built SPA is same-origin and needs none.

    Hardcoding the Vite port means a second checkout on :5174, or a deploy on a
    real hostname, silently fails CORS with no setting to turn.
    """
    configured = os.environ.get("PLUMB_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    port = os.environ.get("PLUMB_DEV_PORT", "5173").strip() or "5173"
    return [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]


app = FastAPI(title="plumb", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
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
    return llm.current_provider()


def _model() -> str:
    return llm.current_model()


def _session_from_pin(con: duckdb.DuckDBPyConnection, tables: list) -> Session:
    guard.safe_connection(con)
    pin = llm.env_pin()
    return Session(
        con=con,
        tables=tables,
        provider=pin.provider,
        model=pin.model,
        endpoint_url=pin.url,
        endpoint_key=pin.key,
        endpoint_host=pin.host,
        endpoint_ip=pin.ip,
        preset_id=pin.preset_id,
    )


def _log_turn(session_id: str, question: str, response: AskResponse) -> None:
    row_count = len(response.rows) if response.rows is not None else 0
    verified = False
    if response.route == "answer" and response.rows is not None:
        verified = narrate.verify_narration(response.narration or "", response.rows)
    panel_sql: list[str | None] = []
    if response.route == "dashboard" and response.panels:
        row_count = sum(len(p.rows or []) for p in response.panels)
        panel_sql = [p.sql for p in response.panels]
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
            "model": response.model or _model(),
            "provider": response.provider or _provider(),
            "host": response.endpoint_host,
            "guard_errors": [],
            # Distinct from guard_errors on purpose: a rate limit says nothing
            # about the SQL or the data, so it must not read as one.
            "error_code": response.error_code,
            "tables_sent": response.tables_sent,
            "definitions_applied": dict(response.definitions_applied),
            "narration_verified": verified,
            # From the advice, not the spec: a spec with value labels is
            # layered, so there is no top-level mark to read a kind off.
            "chart_kind": (
                response.chart_advice.rendered if response.chart_advice else None
            ),
            "chart_rendered": response.chart is not None,
            "panel_count": len(response.panels) if response.panels else 0,
            "panel_sql": panel_sql,
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


@app.get("/api/models")
def get_models(session_id: str | None = None) -> dict[str, object]:
    session = store.get(session_id) if session_id else None
    return llm.catalog(session)


@app.post("/api/models")
def set_models(body: ModelBody) -> dict[str, object]:
    try:
        llm.configure(body.provider, body.model)
    except ValueError as e:
        raise AppError("invalid_model", str(e), 400) from e
    log.info("model pin: provider=%s model=%s", _provider(), _model())
    return llm.catalog()


@app.post("/api/session")
def create_session() -> dict[str, str]:
    """Empty session so the UI can chat or switch models before any upload."""
    con = duckdb.connect(database=":memory:")
    session_id = store.create(_session_from_pin(con, []))
    return {"session_id": session_id}


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
        session_id = store.create(_session_from_pin(con, tables))
        dumped = [t.model_dump() for t in tables]
        return {
            "session_id": session_id,
            "tables": dumped,
            "suggestions": suggestions.suggest_questions(tables),
        }
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


def _raise_provider_error(exc: Exception) -> None:
    if isinstance(exc, EndpointError):
        raise AppError(exc.code, exc.message, 400) from exc
    if isinstance(exc, llm.RateLimitError):
        raise AppError("provider_rate_limited", str(exc), 429) from exc
    if isinstance(exc, llm.LLMError):
        raise AppError("provider_unreachable", str(exc), 400) from exc
    if isinstance(exc, ValueError):
        raise AppError("invalid_model", str(exc), 400) from exc
    raise AppError("invalid_model", str(exc), 400) from exc


@app.post("/api/session/{session_id}/provider/test")
def test_provider(session_id: str, body: ProbeBody) -> dict[str, object]:
    _require(session_id)
    try:
        inspected = llm.probe(body.url, body.key, body.model)
    except Exception as e:
        _raise_provider_error(e)
    return {"ok": True, "host": inspected.host, "model": body.model}


@app.post("/api/session/{session_id}/provider")
def set_provider(session_id: str, body: ProviderBody) -> dict[str, object]:
    session = _require(session_id)
    lock = store.lock_for(session_id)
    if lock is None:
        raise AppError("session_not_found", f"no session {session_id}", 404)
    with lock:
        try:
            pin = llm.apply_session_provider(
                session, body.provider, body.model, url=body.url, key=body.key
            )
        except Exception as e:
            _raise_provider_error(e)
    log.info(
        "session provider: session=%s provider=%s model=%s host=%s",
        session_id,
        pin.preset_id or pin.provider,
        pin.model,
        pin.host,
    )
    return llm.catalog(session)


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


@app.get("/api/session/{session_id}/suggestions")
def session_suggestions(session_id: str) -> dict[str, list[str]]:
    session = _require(session_id)
    return {"suggestions": suggestions.suggest_questions(session.tables)}


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
