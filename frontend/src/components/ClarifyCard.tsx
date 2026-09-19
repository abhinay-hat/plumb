import { useState } from "react";
import type { AskResponse } from "../types";

interface Props {
  response: AskResponse;
  busy: boolean;
  onChoose: (definition: string) => void;
}

export function ClarifyCard({ response, busy, onChoose }: Props) {
  const [free, setFree] = useState("");
  const options = response.clarify_options ?? [];

  return (
    <article className="bg-transparent text-ticket">
      <header className="flex items-center justify-between px-4 py-2">
        <span className="stamp text-ticket">Method</span>
        <span className="font-mono text-[10px] tabular-nums text-ticket/80">
          {response.elapsed_ms} ms
        </span>
      </header>
      <p className="px-4 pt-2 text-[18px] font-medium leading-[1.4] text-ticket">
        {response.clarify_question}
      </p>
      <p className="px-4 pt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-ticket/80">
        Pick a reading — plumb will not guess
      </p>
      <div className="flex flex-col gap-2 px-4 py-4">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            disabled={busy}
            onClick={() => onChoose(option)}
            className="border border-ticket/30 bg-ticket px-3 py-2.5 text-left text-[13px] leading-5 text-ink hover:border-ticket disabled:opacity-50"
          >
            {option}
          </button>
        ))}
      </div>
      <form
        className="flex gap-2 border-t border-ticket/20 px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          const text = free.trim();
          if (!text) return;
          onChoose(text);
          setFree("");
        }}
      >
        <input
          value={free}
          onChange={(e) => setFree(e.target.value)}
          disabled={busy}
          placeholder="Or write the definition yourself"
          className="min-w-0 flex-1 border border-ticket/40 bg-clarify px-3 py-2 text-[13px] text-ticket caret-ticket outline-none placeholder:text-ticket/70 focus:border-ticket"
        />
        <button
          type="submit"
          disabled={busy || !free.trim()}
          className="bg-ticket px-3 py-2 font-mono text-[11px] uppercase tracking-wide text-clarify disabled:opacity-50"
        >
          Use this
        </button>
      </form>
    </article>
  );
}
