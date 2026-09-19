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
    <div className="flex flex-col gap-2">
      {tables.map((table) => {
        const expanded = open[table.name] !== false;
        return (
          <section key={table.name} className="border border-line bg-ticket">
            <button
              type="button"
              className="flex w-full items-baseline justify-between gap-2 px-2.5 py-1.5 text-left hover:bg-panel"
              onClick={() =>
                setOpen((prev) => ({ ...prev, [table.name]: !expanded }))
              }
              aria-expanded={expanded}
            >
              <span className="font-mono text-[12px] font-medium text-ink">{table.name}</span>
              <span className="font-mono text-[10px] tabular-nums text-muted">
                {table.row_count.toLocaleString()} rows
              </span>
            </button>
            {expanded ? (
              <ul className="border-t border-line">
                {table.columns.map((col) => (
                  <li
                    key={col.name}
                    className="border-b border-line px-2.5 py-1.5 last:border-b-0"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-mono text-[11px] text-ink">{col.name}</span>
                      <span className="font-mono text-[10px] uppercase tracking-wide text-muted">
                        {col.dtype}
                      </span>
                    </div>
                    {col.samples.length > 0 ? (
                      <p className="mt-0.5 truncate font-mono text-[10px] text-muted">
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
