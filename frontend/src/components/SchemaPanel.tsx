import { useState } from "react";
import type { TableInfo } from "../types";

interface Props {
  tables: TableInfo[];
}

function tableTitle(table: TableInfo): string {
  const short = table.display_name?.trim() || table.sheet_name?.trim();
  return short || table.name;
}

function formatRows(count: number): string {
  return `${count.toLocaleString()} row${count === 1 ? "" : "s"}`;
}

export function SchemaPanel({ tables }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(tables.map((t) => [t.name, true])),
  );

  return (
    <div className="schema-panel flex flex-col gap-2.5">
      <p className="stamp px-0.5 text-muted">Schema</p>
      {tables.map((table) => {
        const expanded = open[table.name] !== false;
        const title = tableTitle(table);
        const showInternal = title !== table.name;

        return (
          <section key={table.name} className="schema-table border border-line bg-ticket">
            <button
              type="button"
              className="schema-table-head flex w-full min-w-0 items-start justify-between gap-2 px-3 py-2.5 text-left hover:bg-panel"
              onClick={() =>
                setOpen((prev) => ({ ...prev, [table.name]: !expanded }))
              }
              aria-expanded={expanded}
            >
              <span className="min-w-0 flex-1">
                <span className="block break-words font-mono text-[12px] font-medium leading-snug text-ink">
                  {title}
                </span>
                {showInternal ? (
                  <span
                    className="mt-1 block break-all font-mono text-[9px] leading-tight text-muted/75"
                    title={table.name}
                  >
                    {table.name}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0 pt-0.5 font-mono text-[10px] tabular-nums text-muted">
                {formatRows(table.row_count)}
              </span>
            </button>
            {expanded ? (
              <ul className="border-t border-line">
                {table.columns.map((col, index) => (
                  <li
                    key={col.name}
                    className={[
                      "schema-column px-3 py-2",
                      index < table.columns.length - 1 ? "border-b border-line/70" : "",
                    ].join(" ")}
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <span className="min-w-0 break-words font-mono text-[11px] leading-snug text-ink">
                        {col.name}
                      </span>
                      <span className="shrink-0 font-mono text-[9px] uppercase tracking-wide text-muted">
                        {col.dtype}
                      </span>
                    </div>
                    {col.samples.length > 0 ? (
                      <p className="mt-1 break-words font-mono text-[10px] leading-relaxed text-muted">
                        {col.samples.join(" · ")}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
