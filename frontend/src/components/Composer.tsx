import { useState } from "react";

interface Props {
  disabled: boolean;
  onSubmit: (question: string) => void;
  placeholder?: string;
}

export function Composer({ disabled, onSubmit, placeholder = "Ask this sheet" }: Props) {
  const [value, setValue] = useState("");

  return (
    <form
      className="flex shrink-0 items-end gap-3 border-t border-line bg-chassis px-4 py-2.5 sm:px-5 sm:py-3"
      onSubmit={(e) => {
        e.preventDefault();
        const question = value.trim();
        if (!question || disabled) return;
        onSubmit(question);
        setValue("");
      }}
    >
      <label className="flex min-w-0 flex-1 items-baseline gap-3">
        <span className="stamp shrink-0 text-answer">Run</span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled}
          aria-label="Question"
          placeholder={placeholder}
          className="min-w-0 flex-1 border-0 border-b border-line bg-transparent py-1.5 text-[15px] text-ink outline-none placeholder:text-muted focus:border-ink disabled:opacity-50"
        />
      </label>
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="shrink-0 bg-ink px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ticket hover:bg-answer disabled:bg-line disabled:text-muted"
      >
        Ask
      </button>
    </form>
  );
}
