interface Props {
  message: string;
  onRetry: () => void;
}

export function ErrorCard({ message, onRetry }: Props) {
  return (
    <article className="border border-line bg-white px-4 py-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
        Could not reach plumb
      </p>
      <p className="mt-2 font-sans text-[13px] text-ink">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 border border-ink bg-ink px-3 py-1.5 font-mono text-[11px] uppercase tracking-wide text-paper"
      >
        Retry
      </button>
    </article>
  );
}
