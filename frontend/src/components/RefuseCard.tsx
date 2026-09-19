import type { AskResponse } from "../types";

interface Props {
  response: AskResponse;
}

export function RefuseCard({ response }: Props) {
  return (
    <article className="border-0 bg-transparent">
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <span className="stamp text-refuse">Out of range</span>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {response.elapsed_ms} ms
        </span>
      </header>
      <p className="px-4 py-4 text-[16px] leading-[1.5] text-muted">
        {response.refuse_reason}
      </p>
    </article>
  );
}
