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
    <article className="border-0 bg-transparent">
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <span className="stamp text-muted">Recording</span>
        <span className="font-mono text-[11px] tabular-nums text-ink">{seconds}s</span>
      </header>
      <div className="px-4 py-5">
        <div className="pen-trace" />
      </div>
    </article>
  );
}
