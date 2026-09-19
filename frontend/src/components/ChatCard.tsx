import type { AskResponse } from "../types";

interface Props {
  response: AskResponse;
}

export function ChatCard({ response }: Props) {
  return (
    <article className="border-0 bg-transparent">
      <header className="flex items-center justify-between border-b border-line/80 px-4 py-2.5">
        <span className="stamp text-answer">Reply</span>
        <span className="font-mono text-[10px] tabular-nums text-muted">
          {response.endpoint_host || response.provider}
          {response.model ? ` · ${response.model}` : ""} · {response.elapsed_ms} ms
        </span>
      </header>
      <p className="px-4 py-4 text-[15px] leading-6 text-ink">{response.reply}</p>
    </article>
  );
}
