interface Props {
  message: string;
  onRetry: () => void;
}

export function ErrorCard({ message, onRetry }: Props) {
  return (
    <article className="border-0 bg-transparent">
      <header className="border-b border-line px-4 py-2">
        <span className="stamp text-ink">Fault</span>
      </header>
      <p className="px-4 pt-4 text-[13px] leading-5 text-ink">{message}</p>
      <div className="px-4 py-4">
        <button
          type="button"
          onClick={onRetry}
          className="bg-ink px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ticket hover:bg-answer"
        >
          Retry
        </button>
      </div>
    </article>
  );
}
