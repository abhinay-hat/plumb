interface Props {
  onExample?: (question: string) => void;
  /** No spreadsheet yet — offer chat prompts to test the model. */
  preUpload?: boolean;
  /** Schema-derived or chat starters; must come from the caller. */
  examples: string[];
}

export function EmptyState({ onExample, preUpload, examples }: Props) {
  return (
    <div className="flex h-full flex-col justify-center px-1 py-6 sm:py-10">
      <h1 className="max-w-xl font-sans text-[34px] font-semibold leading-[1.12] tracking-[-0.03em] text-ink">
        {preUpload
          ? "Say hi. Or upload a sheet."
          : onExample
            ? "Ask in English. Check the SQL."
            : "Upload a sheet. Ask in English. Check the work."}
      </h1>
      <p className="mt-4 max-w-[65ch] text-[14px] leading-6 text-muted">
        {preUpload
          ? "Try a greeting to confirm the model is wired up. Data questions need a spreadsheet first."
          : onExample
            ? "plumb will answer, ask what a term means, or refuse. It does not guess."
            : "plumb answers, asks for a definition, or says the columns cannot support the question. It does not guess."}
      </p>
      {onExample && examples.length > 0 ? (
        <ul className="mt-8 max-w-lg space-y-2">
          {examples.map((q) => (
            <li key={q}>
              <button
                type="button"
                onClick={() => onExample(q)}
                className="w-full border border-line bg-ticket px-3 py-2.5 text-left text-[13px] text-ink hover:border-ink hover:bg-panel"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
