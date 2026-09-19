import { lazy, Suspense, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import type { AskResponse, Cell } from "../types";

const VegaLite = lazy(() =>
  import("react-vega").then((mod) => ({ default: mod.VegaEmbed })),
);

interface Props {
  response: AskResponse;
}

function isNumeric(value: Cell): boolean {
  return typeof value === "number" && Number.isFinite(value);
}

function formatCell(value: Cell): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : String(value);
  }
  return value;
}

function withValues(
  spec: Record<string, unknown>,
  columns: string[],
  rows: Cell[][],
): VisualizationSpec {
  const values = rows.map((row) => {
    const rec: Record<string, Cell> = {};
    columns.forEach((col, i) => {
      rec[col] = row[i] ?? null;
    });
    return rec;
  });
  return {
    ...spec,
    data: { values },
    width: "container",
    autosize: { type: "fit", contains: "padding" },
  } as VisualizationSpec;
}

export function AnswerCard({ response }: Props) {
  const [copied, setCopied] = useState(false);
  const columns = response.columns ?? [];
  const rows = response.rows ?? [];
  const defs = Object.entries(response.definitions_applied);

  async function copySql() {
    if (!response.sql) return;
    await navigator.clipboard.writeText(response.sql);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <article className="border border-line bg-ticket">
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <span className="stamp text-answer">Answer</span>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {response.elapsed_ms} ms
        </span>
      </header>
      {response.narration ? (
        <p className="px-4 pt-4 text-[16px] leading-[1.5] text-ink">
          {response.narration}
        </p>
      ) : null}
      {defs.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 px-4 pt-3">
          {defs.map(([term, meaning]) => (
            <span
              key={term}
              className="border border-line bg-panel px-2 py-0.5 font-mono text-[11px] text-muted"
            >
              {term} = {meaning}
            </span>
          ))}
        </div>
      ) : null}
      {columns.length > 0 ? (
        <div className="mx-4 my-4 max-h-72 overflow-auto border border-line">
          <table className="w-full border-collapse text-left">
            <thead className="sticky top-0 bg-panel">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    className="border-b border-line px-3 py-2 font-mono text-[11px] font-medium text-muted"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? "bg-ticket" : "bg-panel"}>
                  {columns.map((col, j) => {
                    const value = row[j] ?? null;
                    return (
                      <td
                        key={col}
                        className={[
                          "border-b border-line px-3 py-1.5 font-mono text-[12px] text-ink",
                          isNumeric(value) ? "text-right tabular-nums" : "",
                        ].join(" ")}
                      >
                        {formatCell(value)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {response.chart && columns.length > 0 ? (
        <div className="min-w-0 overflow-hidden px-4 pb-4">
          <Suspense fallback={<div className="h-48 bg-panel" aria-hidden />}>
            <VegaLite
              spec={withValues(response.chart, columns, rows)}
              options={{ actions: false }}
            />
          </Suspense>
        </div>
      ) : null}
      {response.sql ? (
        <details className="border-t border-line">
          <summary className="cursor-pointer px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
            Show SQL
          </summary>
          <div className="relative border-t border-line bg-panel px-4 py-3">
            <button
              type="button"
              onClick={() => {
                void copySql();
              }}
              className="absolute right-3 top-3 stamp text-answer hover:text-ink"
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <pre className="overflow-x-auto whitespace-pre-wrap pr-14 font-mono text-[12px] leading-5 text-ink">
              {response.sql}
            </pre>
          </div>
        </details>
      ) : null}
    </article>
  );
}
