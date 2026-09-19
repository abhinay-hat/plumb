interface Props {
  message: string;
  onRetry: () => void;
}

export function ErrorCard({ message, onRetry }: Props) {
  return (
    <article className="border border-line bg-ticket px-4 py-4">
      <p className="text-[13px] leading-5 text-ink">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 bg-ink px-3 py-1.5 font-mono text-[11px] uppercase tracking-wide text-ticket hover:bg-answer"
      >
        Retry
      </button>
    </article>
  );
}
