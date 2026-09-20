import { lazy, Suspense, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import type { AskResponse, Cell, Panel } from "../types";

const VegaLite = lazy(() =>
  import("react-vega").then((mod) => ({ default: mod.VegaEmbed })),
);

interface Props {
  response: AskResponse;
  onAsk?: (question: string) => void;
}

function formatCell(value: Cell): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
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
    height: 180,
    autosize: { type: "fit", contains: "padding" },
  } as VisualizationSpec;
}

function PanelCell({ panel }: { panel: Panel }) {
  const [showSql, setShowSql] = useState(false);
  const columns = panel.columns ?? [];
  const rows = panel.rows ?? [];

  if (panel.error_code) {
    return (
      <div className="border border-line bg-panel p-3">
        <p className="font-sans text-[13px] font-medium text-ink">{panel.title}</p>
        <p className="mt-2 font-mono text-[11px] text-muted">
          Panel failed ({panel.error_code.replace(/_/g, " ")}).
        </p>
      </div>
    );
  }

  return (
    <div className="border border-line bg-ticket">
      <header className="border-b border-line px-3 py-2">
        <p className="font-sans text-[13px] font-medium text-ink">{panel.title}</p>
        {panel.finding ? (
          <p className="mt-1 text-[12px] leading-5 text-muted">{panel.finding}</p>
        ) : null}
      </header>
      {panel.chart && columns.length > 0 ? (
        <div className="min-w-0 overflow-hidden px-2 py-2">
          <Suspense fallback={<div className="h-40 bg-panel" aria-hidden />}>
            <VegaLite
              spec={withValues(panel.chart, columns, rows)}
              options={{ actions: false }}
            />
          </Suspense>
        </div>
      ) : rows.length > 0 && columns.length > 0 ? (
        <div className="overflow-x-auto px-2 py-2">
          <table className="w-full border-collapse font-mono text-[11px]">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                {columns.map((col) => (
                  <th key={col} className="px-2 py-1 font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 8).map((row, i) => (
                <tr key={i} className="border-b border-line/60">
                  {columns.map((col, j) => (
                    <td key={col} className="px-2 py-1 tabular-nums">
                      {formatCell(row[j] ?? null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {panel.sql ? (
        <div className="border-t border-line/80 px-3 py-2">
          <button
            type="button"
            className="font-mono text-[10px] uppercase tracking-wider text-answer hover:underline"
            onClick={() => setShowSql((open) => !open)}
          >
            {showSql ? "Hide SQL" : "Show SQL"}
          </button>
          {showSql ? (
            <pre className="mt-2 overflow-x-auto bg-panel p-2 font-mono text-[11px] text-ink">
              {panel.sql}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function DashboardCard({ response, onAsk }: Props) {
  const panels = response.panels ?? [];
  const followUps = response.follow_ups ?? [];

  return (
    <article className="border-0 bg-transparent">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-2">
        <span className="stamp text-answer">Dashboard</span>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {panels.length} panel{panels.length === 1 ? "" : "s"} · {response.elapsed_ms} ms ·{" "}
          {response.endpoint_host || response.provider}
          {response.model ? ` · ${response.model}` : ""}
        </span>
      </header>
      {response.summary ? (
        <p className="px-4 pt-4 text-[15px] leading-[1.5] text-ink">{response.summary}</p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 px-4 py-4 md:grid-cols-2">
        {panels.map((panel, index) => (
          <PanelCell key={`${panel.title}-${index}`} panel={panel} />
        ))}
      </div>
      {followUps.length > 0 ? (
        <div className="border-t border-line/80 px-4 py-3">
          <p className="stamp mb-2 text-muted">Next</p>
          <div className="flex flex-wrap gap-2">
            {followUps.map((question) => (
              <button
                key={question}
                type="button"
                className="border border-line bg-panel px-2 py-1 text-left font-sans text-[12px] text-ink hover:border-answer"
                onClick={() => onAsk?.(question)}
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}
