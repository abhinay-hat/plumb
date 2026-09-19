interface Props {
  onExample?: (question: string) => void;
}

const EXAMPLES = [
  "How many employees in each department?",
  "Who are our top performers?",
  "What's the average salary by location?",
];

export function EmptyState({ onExample }: Props) {
  return (
    <div className="flex h-full flex-col justify-center px-2 py-10">
      <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">
        Spreadsheet questions, with the SQL
      </p>
      <h1 className="mt-3 max-w-xl font-serif text-[34px] leading-[1.15] tracking-tight text-ink">
        Upload a sheet. Ask in English. Check the work.
      </h1>
      <p className="mt-4 max-w-lg text-[14px] leading-6 text-muted">
        plumb answers, asks for a definition, or says the columns cannot support
        the question. It does not guess.
      </p>
      <ol className="mt-8 max-w-lg space-y-2">
        {EXAMPLES.map((q, i) => (
          <li key={q}>
            <button
              type="button"
              onClick={() => onExample?.(q)}
              disabled={!onExample}
              className="w-full border border-line bg-white px-3 py-2.5 text-left hover:border-ink disabled:cursor-default"
            >
              <span className="mr-3 font-mono text-[11px] text-muted">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-[13px] text-ink">{q}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
