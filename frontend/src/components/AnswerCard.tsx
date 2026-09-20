import { lazy, Suspense, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import type { AskResponse, Cell } from "../types";

const VegaLite = lazy(() =>
  import("react-vega").then((mod) => ({ default: mod.VegaEmbed })),
);

interface Props {
  response: AskResponse;
  /** Asking a follow-up is the same as typing it; the composer owns the turn. */
  onAsk?: (question: string) => void;
}

function isNumeric(value: Cell): boolean {
  return typeof value === "number" && Number.isFinite(value);
}

/** Decimals that help, read off the magnitude — same rule as chart.number_format. */
function decimalsFor(value: number): number {
  const size = Math.abs(value);
  if (size >= 1000) return 0;
  if (size >= 10) return 1;
  return 2;
}

function formatCell(value: Cell): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString();
    // An average lands on 664.8717948717949; sixteen digits of float noise is
    // not extra precision, it is the division showing through. The full value
    // stays in the cell's title so nothing is actually hidden.
    return value.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: decimalsFor(value),
    });
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

export function AnswerCard({ response, onAsk }: Props) {
  const [copied, setCopied] = useState(false);
  const columns = response.columns ?? [];
  const rows = response.rows ?? [];
  const defs = Object.entries(response.definitions_applied);
  const advice = response.chart_advice;
  const followUps = response.follow_ups ?? [];

  async function copySql() {
    if (!response.sql) return;
    await navigator.clipboard.writeText(response.sql);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <article className="border-0 bg-transparent">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-2">
        <span className="stamp text-answer">Answer</span>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {rows.length} row{rows.length === 1 ? "" : "s"} · {response.elapsed_ms} ms ·{" "}
          {response.endpoint_host || response.provider}
          {response.model ? ` · ${response.model}` : ""}
          {response.chart ? " · chart" : ""}
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
      {response.chart && columns.length > 0 ? (
        <div className="min-w-0 overflow-hidden border-t border-line/80 px-4 py-4">
          <p className="stamp mb-3 text-answer">
            Chart{advice?.rendered ? ` · ${advice.rendered}` : ""}
          </p>
          <Suspense fallback={<div className="h-48 bg-panel" aria-hidden />}>
            <VegaLite
              spec={withValues(response.chart, columns, rows)}
              options={{ actions: false }}
            />
          </Suspense>
        </div>
      ) : null}
      {advice && (advice.reason || advice.unsupported) ? (
        <div className="border-t border-line/80 px-4 py-3">
          <p className="stamp mb-1.5 text-muted">
            {advice.kind === "none"
              ? "No chart"
              : advice.rendered === advice.kind
                ? `Why a ${advice.kind}`
                : `Better as a ${advice.kind}`}
          </p>
          <p className="text-[13px] leading-[1.5] text-muted">{advice.reason}</p>
          {advice.unsupported ? (
            <p className="mt-1.5 text-[13px] leading-[1.5] text-clarify">
              These columns describe a {advice.unsupported}, which plumb does not
              render — the {advice.kind === "none" ? "table" : advice.kind} above is
              the closest honest view.
            </p>
          ) : null}
          {advice.alternatives.length > 0 && onAsk ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {advice.alternatives.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => onAsk(`Show this as a ${kind} chart.`)}
                  className="border border-line bg-panel px-2 py-0.5 font-mono text-[11px] text-muted hover:border-answer hover:text-ink"
                >
                  as {kind}
                </button>
              ))}
            </div>
          ) : null}
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
                        title={value === null ? undefined : String(value)}
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
      {followUps.length > 0 && onAsk ? (
        <div className="border-t border-line/80 px-4 py-3">
          <p className="stamp mb-2 text-muted">Next</p>
          <div className="flex flex-wrap gap-1.5">
            {followUps.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onAsk(question)}
                className="border border-line bg-panel px-2 py-1 text-left text-[12px] text-muted hover:border-answer hover:text-ink"
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {response.sql ? (
        <details className="border-t border-line">
          <summary className="cursor-pointer px-4 py-2 stamp text-muted hover:text-ink">
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
