import { useCallback, useMemo, useState } from "react";
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
import { UploadZone } from "./components/UploadZone";
import type { AskResponse, AuditEntry, TableInfo } from "./types";
import { ApiRequestError } from "./types";

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

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [audit, setAudit] = useState<AuditEntry[]>([]);

  const pending = useMemo(
    () => turns.some((t) => t.kind === "pending"),
    [turns],
  );

  const refreshAudit = useCallback(async (id: string) => {
    try {
      setAudit(await api.auditLog(id));
    } catch (err) {
      console.error(err);
    }
  }, []);

  async function onFiles(files: File[]) {
    setUploading(true);
    setUploadError(null);
    try {
      const result = await api.upload(files);
      setSessionId(result.session_id);
      setTables(result.tables);
      setTurns([]);
      setAudit([]);
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
      await refreshAudit(sessionId);
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

  // The planner names the term it clarified. The frontend never guesses:
  // a guessed key files the definition where the planner will never look,
  // and the same clarify card comes back forever.
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

  const tableLabel = sessionId
    ? `${tables.length} table${tables.length === 1 ? "" : "s"}`
    : "no file";

  return (
    <div className="flex h-svh min-h-0 w-full overflow-hidden bg-channel max-lg:flex-col">
      <aside className="flex w-[272px] shrink-0 flex-col bg-chassis max-lg:w-full max-lg:max-h-[30vh] max-lg:border-b max-lg:border-line">
        <div className="border-b border-line px-4 py-4">
          <p className="font-sans text-[22px] font-semibold leading-none tracking-tight text-ink">
            plumb
          </p>
          <p className="mt-1.5 font-mono text-[11px] text-muted">
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

      <div className="w-2 shrink-0 bg-channel max-lg:hidden" aria-hidden />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-chassis px-5">
          <p className="truncate font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
            {tableLabel}
          </p>
          <button
            type="button"
            disabled={!sessionId}
            aria-expanded={auditOpen}
            onClick={() => {
              setAuditOpen(true);
              if (sessionId) void refreshAudit(sessionId);
            }}
            className="stamp text-ink hover:text-answer disabled:text-muted"
          >
            Audit
          </button>
        </header>

        <div className="chart-bed min-h-0 flex-1 overflow-y-auto px-5 py-6">
          {!sessionId ? (
            <EmptyState />
          ) : turns.length === 0 ? (
            <EmptyState onExample={(q) => void runAsk(q)} />
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-5">
              {turns.map((turn) => {
                if (turn.kind === "user") {
                  return (
                    <p
                      key={turn.id}
                      className="flex gap-3 font-mono text-[12px] leading-5 text-muted"
                    >
                      <span className="shrink-0 uppercase tracking-[0.14em]">Q</span>
                      <span className="font-sans text-[14px] text-ink">{turn.question}</span>
                    </p>
                  );
                }
                if (turn.kind === "pending") {
                  return <PendingCard key={turn.id} started={turn.started} />;
                }
                if (turn.kind === "error") {
                  return (
                    <ErrorCard
                      key={turn.id}
                      message={turn.message}
                      onRetry={() => void runAsk(turn.question)}
                    />
                  );
                }
                if (turn.response.route === "clarify") {
                  return (
                    <ClarifyCard
                      key={turn.id}
                      response={turn.response}
                      busy={busy}
                      onChoose={(definition) => void onClarify(turn, definition)}
                    />
                  );
                }
                if (turn.response.route === "refuse") {
                  return <RefuseCard key={turn.id} response={turn.response} />;
                }
                if (turn.response.route === "chat") {
                  return <ChatCard key={turn.id} response={turn.response} />;
                }
                if (turn.response.route === "error") {
                  return (
                    <ErrorCard
                      key={turn.id}
                      message={
                        turn.response.error_message ??
                        "Something went wrong before the question was answered."
                      }
                      onRetry={() => void runAsk(turn.question)}
                    />
                  );
                }
                return <AnswerCard key={turn.id} response={turn.response} />;
              })}
            </div>
          )}
        </div>

        <Composer
          disabled={!sessionId || busy || pending}
          onSubmit={(q) => void runAsk(q)}
        />
      </main>

      <AuditDrawer open={auditOpen} entries={audit} onClose={() => setAuditOpen(false)} />
    </div>
  );
}
