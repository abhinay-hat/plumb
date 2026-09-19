import type { AskResponse } from "../types";

interface Props {
  response: AskResponse;
}

export function RefuseCard({ response }: Props) {
  return (
    <article className="border border-line bg-panel">
      <header className="flex items-center justify-between px-4 py-2">
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-refuse">
          Outside this sheet
        </span>
        <span className="font-mono text-[10px] text-muted">{response.elapsed_ms} ms</span>
      </header>
      <p className="px-4 py-4 font-serif text-[16px] leading-[1.55] text-muted">
        {response.refuse_reason}
      </p>
    </article>
  );
}
