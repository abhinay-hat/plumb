import { useEffect, useState } from "react";

interface Props {
  started: number;
}

export function PendingCard({ started }: Props) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const tick = () => setSeconds(Math.floor((Date.now() - started) / 1000));
    tick();
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [started]);

  return (
    <article className="border border-line bg-white px-4 py-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
          Running
        </span>
        <span className="font-mono text-[11px] tabular-nums text-ink">{seconds}s</span>
      </div>
      <div className="mt-3 space-y-2">
        <div className="h-3 w-5/6 animate-pulse bg-line/70" />
        <div className="h-3 w-3/5 animate-pulse bg-line/50" />
        <div className="h-24 w-full animate-pulse bg-panel" />
      </div>
    </article>
  );
}
