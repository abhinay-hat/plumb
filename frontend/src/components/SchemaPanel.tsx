import { useState } from "react";
import type { TableInfo } from "../types";

interface Props {
  tables: TableInfo[];
}

export function SchemaPanel({ tables }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(tables.map((t) => [t.name, true])),
  );

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
        Schema
      </p>
      {tables.map((table) => {
        const expanded = open[table.name] !== false;
        return (
          <section key={table.name} className="border border-line bg-panel">
            <button
              type="button"
              className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left"
              onClick={() =>
                setOpen((prev) => ({ ...prev, [table.name]: !expanded }))
              }
              aria-expanded={expanded}
            >
              <span className="font-mono text-[13px] font-medium text-ink">{table.name}</span>
              <span className="font-mono text-[11px] text-muted">
                {table.row_count.toLocaleString()} rows
              </span>
            </button>
            {expanded ? (
              <ul className="border-t border-line">
                {table.columns.map((col) => (
                  <li
                    key={col.name}
                    className="border-b border-line/70 px-3 py-2 last:border-b-0"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-mono text-[12px] text-ink">{col.name}</span>
                      <span className="font-mono text-[10px] uppercase tracking-wide text-muted">
                        {col.dtype}
                      </span>
                    </div>
                    {col.samples.length > 0 ? (
                      <p className="mt-1 truncate font-mono text-[11px] text-muted">
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
