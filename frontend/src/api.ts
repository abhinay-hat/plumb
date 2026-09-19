import type {
  AskResponse,
  AuditEntry,
  ModelCatalog,
  SessionResult,
  SettleResult,
  SuggestionsResult,
  TableInfo,
  UploadResult,
} from "./types";
import { ApiRequestError } from "./types";

/** Called when the API no longer has this session (reload, eviction). */
type SessionRefresh = () => Promise<string>;

let refreshSession: SessionRefresh | null = null;

export function bindSessionRefresh(fn: SessionRefresh | null): void {
  refreshSession = fn;
}

async function withSession<T>(
  sessionId: string,
  call: (id: string) => Promise<T>,
): Promise<T> {
  try {
    return await call(sessionId);
  } catch (err) {
    if (
      err instanceof ApiRequestError &&
      err.code === "session_not_found" &&
      refreshSession
    ) {
      const fresh = await refreshSession();
      return await call(fresh);
    }
    throw err;
  }
}

interface ErrorBody {
  code?: string;
  message?: string;
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let code = "http_error";
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as ErrorBody;
      if (typeof body.code === "string" && body.code) code = body.code;
      if (typeof body.message === "string" && body.message) message = body.message;
    } catch (err) {
      throw new ApiRequestError(code, `${message} (${String(err)})`);
    }
    throw new ApiRequestError(code, message);
  }
  return (await response.json()) as T;
}

export async function health(): Promise<{ status: string }> {
  return parseJson(await fetch("/api/health"));
}

export async function createSession(): Promise<SessionResult> {
  return parseJson(await fetch("/api/session", { method: "POST" }));
}

export async function upload(files: File[]): Promise<UploadResult> {
  const body = new FormData();
  if (files.length === 1) {
    body.append("file", files[0]);
  } else {
    for (const file of files) body.append("files", file);
  }
  return parseJson(await fetch("/api/upload", { method: "POST", body }));
}

export async function ask(sessionId: string, question: string): Promise<AskResponse> {
  return withSession(sessionId, async (id) =>
    parseJson(
      await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id, question }),
      }),
    ),
  );
}

export async function settle(
  sessionId: string,
  term: string,
  definition: string,
): Promise<SettleResult> {
  return withSession(sessionId, async (id) =>
    parseJson(
      await fetch(`/api/session/${id}/settle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ term, definition }),
      }),
    ),
  );
}

export async function schema(sessionId: string): Promise<TableInfo[]> {
  return withSession(sessionId, async (id) =>
    parseJson(await fetch(`/api/session/${id}/schema`)),
  );
}

export async function sessionSuggestions(sessionId: string): Promise<SuggestionsResult> {
  return withSession(sessionId, async (id) =>
    parseJson(await fetch(`/api/session/${id}/suggestions`)),
  );
}

export async function auditLog(sessionId: string): Promise<AuditEntry[]> {
  return withSession(sessionId, async (id) =>
    parseJson(await fetch(`/api/session/${id}/audit`)),
  );
}

export async function models(sessionId?: string | null): Promise<ModelCatalog> {
  if (sessionId) {
    return withSession(sessionId, async (id) =>
      parseJson(await fetch(`/api/models?session_id=${encodeURIComponent(id)}`)),
    );
  }
  return parseJson(await fetch("/api/models"));
}

export async function setModel(
  provider: string,
  model: string,
  sessionId?: string | null,
): Promise<ModelCatalog> {
  if (sessionId) {
    return setSessionProvider(sessionId, { provider, model });
  }
  return parseJson(
    await fetch("/api/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model }),
    }),
  );
}

export async function setSessionProvider(
  sessionId: string,
  body: { provider: string; model: string; url?: string; key?: string },
): Promise<ModelCatalog> {
  return withSession(sessionId, async (id) =>
    parseJson(
      await fetch(`/api/session/${id}/provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
  );
}

export async function testEndpoint(
  sessionId: string,
  body: { url: string; model: string; key?: string },
): Promise<{ ok: boolean; host: string; model: string }> {
  return withSession(sessionId, async (id) =>
    parseJson(
      await fetch(`/api/session/${id}/provider/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
  );
}
