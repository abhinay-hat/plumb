import type { AskResponse, AuditEntry, SettleResult, TableInfo, UploadResult } from "./types";
import { ApiRequestError } from "./types";

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
  return parseJson(
    await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
    }),
  );
}

export async function settle(
  sessionId: string,
  term: string,
  definition: string,
): Promise<SettleResult> {
  return parseJson(
    await fetch(`/api/session/${sessionId}/settle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ term, definition }),
    }),
  );
}

export async function schema(sessionId: string): Promise<TableInfo[]> {
  return parseJson(await fetch(`/api/session/${sessionId}/schema`));
}

export async function auditLog(sessionId: string): Promise<AuditEntry[]> {
  return parseJson(await fetch(`/api/session/${sessionId}/audit`));
}
