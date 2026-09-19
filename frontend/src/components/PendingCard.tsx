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
    <article className="border border-line bg-ticket px-4 py-4">
      <div className="flex items-center justify-between">
        <span className="stamp text-muted">Recording</span>
        <span className="font-mono text-[11px] tabular-nums text-ink">{seconds}s</span>
      </div>
      <div className="mt-5">
        <div className="pen-trace" />
      </div>
    </article>
  );
}
