import type { AuditEntry } from "../types";

interface Props {
  open: boolean;
  entries: AuditEntry[];
  onClose: () => void;
}

export function AuditDrawer({ open, entries, onClose }: Props) {
  const newestFirst = [...entries].reverse();

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Close audit log"
          className="fixed inset-0 z-30 bg-ink/25"
          onClick={onClose}
        />
      ) : null}
      <aside
        className={[
          "fixed top-0 right-0 z-40 flex h-full w-[360px] max-w-[100vw] flex-col border-l border-line bg-chassis transition-transform",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
        inert={!open || undefined}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="stamp text-ink">Audit</h2>
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-[11px] text-muted hover:text-ink"
          >
            Close
          </button>
        </header>
        <div className="chart-bed min-h-0 flex-1 overflow-y-auto">
          {newestFirst.length === 0 ? (
            <p className="px-4 py-6 text-[13px] text-muted">No turns logged yet.</p>
          ) : (
            newestFirst.map((entry, i) => (
              <section key={`${entry.ts}-${i}`} className="border-b border-line bg-ticket/80 px-4 py-3">
                <p className="text-[13px] text-ink">{entry.question}</p>
                <p className="mt-1 font-mono text-[11px] text-muted">
                  {entry.route}
                  {entry.row_count > 0 ? ` · ${entry.row_count} rows` : ""} · {entry.elapsed_ms}{" "}
                  ms · {entry.provider}
                  {entry.model ? ` · ${entry.model}` : ""}
                </p>
                {entry.error_code ? (
                  <p className="mt-1 font-mono text-[11px] text-clarify">{entry.error_code}</p>
                ) : null}
                {entry.sql ? (
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-4 text-muted">
                    {entry.sql}
                  </pre>
                ) : null}
              </section>
            ))
          )}
        </div>
      </aside>
    </>
  );
}
