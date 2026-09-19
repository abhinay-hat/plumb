import { useEffect, useMemo, useState } from "react";
import * as api from "./api";
import { AnswerCard } from "./components/AnswerCard";
import { AuditDrawer } from "./components/AuditDrawer";
import { ChatCard } from "./components/ChatCard";
import { ClarifyCard } from "./components/ClarifyCard";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { ErrorCard } from "./components/ErrorCard";
import { PendingCard } from "./components/PendingCard";
import { RefuseCard } from "./components/RefuseCard";
import { SchemaPanel } from "./components/SchemaPanel";
import { SessionBar } from "./components/SessionBar";
import { TurnExchange, type TurnRoute } from "./components/TurnExchange";
import { UploadZone } from "./components/UploadZone";
import type { AskResponse, AuditEntry, TableInfo } from "./types";
import { ApiRequestError } from "./types";
import {
  clearWorkspace,
  loadWorkspace,
  type PersistedTurn,
  saveWorkspace,
} from "./workspace";

interface UserTurn {
  id: string;
  kind: "user";
  question: string;
}

interface ModelTurn {
  id: string;
  kind: "model";
  question: string;
  response: AskResponse;
}

interface PendingTurn {
  id: string;
  kind: "pending";
  question: string;
  started: number;
}

interface ErrorTurn {
  id: string;
  kind: "error";
  question: string;
  message: string;
}

type Turn = UserTurn | ModelTurn | PendingTurn | ErrorTurn;

function nextId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function persistableTurns(turns: Turn[]): PersistedTurn[] {
  return turns.filter((turn) => turn.kind !== "pending") as PersistedTurn[];
}

function turnRoute(turn: Exclude<Turn, UserTurn>): TurnRoute {
  if (turn.kind === "pending") return "pending";
  if (turn.kind === "error") return "error";
  return turn.response.route;
}

/** Only prompts that make sense before a spreadsheet is loaded. */
const CHAT_STARTERS = ["Hi", "What can you do?", "How does plumb work?"];

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  useEffect(() => {
    api.bindSessionRefresh(async () => {
      const result = await api.createSession();
      setSessionId(result.session_id);
      setTables([]);
      setBootError(null);
      return result.session_id;
    });

    async function boot() {
      const saved = loadWorkspace();
      if (saved?.turns.length) {
        setTurns(saved.turns);
      }
      if (saved?.sessionId) {
        try {
          const schema = await api.schema(saved.sessionId);
          setSessionId(saved.sessionId);
          setTables(schema);
          setBootError(null);
          return;
        } catch {
          // Server restarted or session evicted — keep turns, mint a new session.
        }
      }
      try {
        const result = await api.createSession();
        setSessionId(result.session_id);
        setBootError(null);
      } catch (err) {
        const message = err instanceof ApiRequestError ? err.message : String(err);
        setBootError(message);
      }
    }

    void boot();
    return () => api.bindSessionRefresh(null);
  }, []);

  useEffect(() => {
    if (!sessionId && turns.length === 0 && tables.length === 0) return;
    saveWorkspace({
      sessionId,
      tables,
      turns: persistableTurns(turns),
    });
  }, [sessionId, tables, turns]);

  useEffect(() => {
    if (!sessionId || tables.length === 0) {
      setSuggestions([]);
      return;
    }
    void api
      .sessionSuggestions(sessionId)
      .then((body) => setSuggestions(body.suggestions))
      .catch(() => setSuggestions([]));
  }, [sessionId, tables]);

  const pending = useMemo(
    () => turns.some((t) => t.kind === "pending"),
    [turns],
  );

  async function startNewSession() {
    if (busy || pending) return;
    try {
      const result = await api.createSession();
      setSessionId(result.session_id);
      setTables([]);
      setSuggestions([]);
      setTurns([]);
      setUploadError(null);
      setAuditOpen(false);
      setAuditEntries([]);
      clearWorkspace();
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setBootError(message);
    }
  }

  async function openAudit() {
    if (!sessionId) return;
    try {
      setAuditEntries(await api.auditLog(sessionId));
      setAuditOpen(true);
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setBootError(message);
    }
  }

  async function onFiles(files: File[]) {
    setUploading(true);
    setUploadError(null);
    try {
      const result = await api.upload(files);
      setSessionId(result.session_id);
      setTables(result.tables);
      setSuggestions(result.suggestions);
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setUploadError(message);
    } finally {
      setUploading(false);
    }
  }

  async function runAsk(question: string) {
    if (!sessionId || busy) return;
    const userId = nextId();
    const pendingId = nextId();
    setBusy(true);
    setTurns((prev) => [
      ...prev,
      { id: userId, kind: "user", question },
      { id: pendingId, kind: "pending", question, started: Date.now() },
    ]);
    try {
      const response = await api.ask(sessionId, question);
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === pendingId
            ? { id: pendingId, kind: "model", question, response }
            : turn,
        ),
      );
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === pendingId
            ? { id: pendingId, kind: "error", question, message }
            : turn,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function onClarify(turn: ModelTurn, definition: string) {
    if (!sessionId) return;
    const term = turn.response.clarify_term ?? turn.question;
    try {
      await api.settle(sessionId, term, definition);
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setTurns((prev) => [
        ...prev,
        { id: nextId(), kind: "error", question: turn.question, message },
      ]);
      return;
    }
    await runAsk(turn.question);
  }

  const tableLabel =
    tables.length === 0
      ? "no file"
      : `${tables.length} table${tables.length === 1 ? "" : "s"}`;

  return (
    <div className="flex h-svh min-h-0 w-full overflow-hidden bg-channel max-lg:flex-col">
      <aside className="flex w-[min(100%,20rem)] shrink-0 flex-col overflow-x-hidden bg-chassis max-lg:w-full max-lg:max-h-[30vh] max-lg:border-b max-lg:border-line">
        <div className="flex h-14 shrink-0 flex-col justify-center border-b border-line px-4">
          <p className="font-sans text-[20px] font-semibold leading-none tracking-tight text-ink">
            plumb
          </p>
          <p className="mt-1 font-mono text-[11px] text-muted">
            answers you can check
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <UploadZone disabled={uploading || busy} onFiles={(files) => void onFiles(files)} />
          {uploadError ? (
            <p className="mt-2 font-mono text-[11px] text-clarify">{uploadError}</p>
          ) : null}
          {tables.length > 0 ? (
            <div className="mt-4">
              <SchemaPanel tables={tables} />
            </div>
          ) : (
            <p className="mt-4 text-[12px] leading-5 text-muted">
              Load a CSV, TSV, or XLSX. Columns and sample values appear here so you
              can confirm the file was read as you expect.
            </p>
          )}
        </div>
      </aside>

      <div className="w-[8px] shrink-0 bg-channel max-lg:hidden" aria-hidden />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-line bg-chassis px-3 py-2 sm:min-h-14 sm:px-5 sm:py-0">
          <p className="min-w-0 shrink-0 stamp text-muted">{tableLabel}</p>
          <SessionBar
            sessionId={sessionId}
            busy={busy || pending}
            disabled={busy || pending}
            onAudit={() => void openAudit()}
            onNewSession={() => void startNewSession()}
          />
        </header>

        <div className="chart-bed min-h-0 flex-1 overflow-y-auto px-5 py-6">
          {bootError ? (
            <p className="font-mono text-[12px] text-clarify">{bootError}</p>
          ) : !sessionId ? (
            <EmptyState examples={[]} />
          ) : turns.length === 0 ? (
            <EmptyState
              preUpload={tables.length === 0}
              examples={tables.length === 0 ? CHAT_STARTERS : suggestions}
              onExample={(q) => void runAsk(q)}
            />
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-6">
              {turns.map((turn) => {
                if (turn.kind === "user") return null;

                const body =
                  turn.kind === "pending" ? (
                    <PendingCard started={turn.started} />
                  ) : turn.kind === "error" ? (
                    <ErrorCard
                      message={turn.message}
                      onRetry={() => void runAsk(turn.question)}
                    />
                  ) : turn.response.route === "clarify" ? (
                    <ClarifyCard
                      response={turn.response}
                      busy={busy}
                      onChoose={(definition) => void onClarify(turn, definition)}
                    />
                  ) : turn.response.route === "refuse" ? (
                    <RefuseCard response={turn.response} />
                  ) : turn.response.route === "chat" ? (
                    <ChatCard response={turn.response} />
                  ) : turn.response.route === "error" ? (
                    <ErrorCard
                      message={
                        turn.response.error_message ??
                        "Something went wrong before the question was answered."
                      }
                      onRetry={() => void runAsk(turn.question)}
                    />
                  ) : (
                    <AnswerCard
                      response={turn.response}
                      onAsk={(question) => {
                        void runAsk(question);
                      }}
                    />
                  );

                return (
                  <TurnExchange key={turn.id} question={turn.question} route={turnRoute(turn)}>
                    {body}
                  </TurnExchange>
                );
              })}
            </div>
          )}
        </div>

        <Composer
          disabled={!sessionId || busy || pending}
          placeholder={tables.length === 0 ? "Say hi or ask anything" : "Ask this sheet"}
          onSubmit={(q) => void runAsk(q)}
        />
      </main>

      <AuditDrawer
        open={auditOpen}
        entries={auditEntries}
        onClose={() => setAuditOpen(false)}
      />
    </div>
  );
}
