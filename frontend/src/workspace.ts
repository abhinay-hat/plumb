import type { AskResponse, TableInfo } from "./types";

const KEY = "plumb.workspace";

export interface PersistedUserTurn {
  id: string;
  kind: "user";
  question: string;
}

export interface PersistedModelTurn {
  id: string;
  kind: "model";
  question: string;
  response: AskResponse;
}

export interface PersistedErrorTurn {
  id: string;
  kind: "error";
  question: string;
  message: string;
}

export type PersistedTurn = PersistedUserTurn | PersistedModelTurn | PersistedErrorTurn;

export interface WorkspaceSnapshot {
  sessionId: string | null;
  tables: TableInfo[];
  turns: PersistedTurn[];
}

export function loadWorkspace(): WorkspaceSnapshot | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as WorkspaceSnapshot;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : null,
      tables: Array.isArray(parsed.tables) ? parsed.tables : [],
      turns: Array.isArray(parsed.turns) ? parsed.turns : [],
    };
  } catch {
    return null;
  }
}

export function saveWorkspace(snapshot: WorkspaceSnapshot): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(snapshot));
  } catch {
    // Quota or private mode — ignore; the live session still works.
  }
}

export function clearWorkspace(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
