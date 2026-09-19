import { useState } from "react";

interface Props {
  disabled: boolean;
  onSubmit: (question: string) => void;
}

export function Composer({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState("");

  return (
    <form
      className="flex gap-2 border-t border-line bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        const question = value.trim();
        if (!question || disabled) return;
        onSubmit(question);
        setValue("");
      }}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder="Ask about the spreadsheet"
        className="min-w-0 flex-1 border border-line bg-paper px-3 py-2.5 text-[14px] text-ink outline-none focus:border-ink disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="border border-ink bg-ink px-4 py-2 font-mono text-[11px] uppercase tracking-wide text-paper disabled:opacity-40"
      >
        Ask
      </button>
    </form>
  );
}
