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
    <article className="border border-clarify/40 bg-clarify-tint shadow-[inset_4px_0_0_0_#b86a2d]">
      <header className="flex items-center justify-between px-4 py-2">
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-clarify">
          Needs a definition
        </span>
        <span className="font-mono text-[10px] text-muted">{response.elapsed_ms} ms</span>
      </header>
      <p className="px-4 pt-2 font-serif text-[18px] leading-[1.5] text-ink">
        {response.clarify_question}
      </p>
      <p className="px-4 pt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
        Pick a reading — plumb will not guess
      </p>
      <div className="flex flex-col gap-2 px-4 py-4">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            disabled={busy}
            onClick={() => onChoose(option)}
            className="border border-clarify/50 bg-white px-3 py-2.5 text-left font-sans text-[13px] leading-5 text-ink hover:border-clarify hover:bg-clarify-tint disabled:opacity-50"
          >
            {option}
          </button>
        ))}
      </div>
      <form
        className="flex gap-2 border-t border-clarify/20 px-4 py-3"
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
          className="min-w-0 flex-1 border border-clarify/30 bg-white px-3 py-2 font-sans text-[13px] text-ink outline-none focus:border-clarify"
        />
        <button
          type="submit"
          disabled={busy || !free.trim()}
          className="border border-clarify bg-clarify px-3 py-2 font-mono text-[11px] uppercase tracking-wide text-white disabled:opacity-50"
        >
          Use this
        </button>
      </form>
    </article>
  );
}
