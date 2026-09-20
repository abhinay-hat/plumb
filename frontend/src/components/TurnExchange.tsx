import type { ReactNode } from "react";
import type { AskResponse } from "../types";

export type TurnRoute = AskResponse["route"] | "pending" | "error";

const RESPONSE_SHELL: Record<TurnRoute, string> = {
  chat: "border-l-ink/40 bg-ticket",
  answer: "border-l-answer bg-ticket",
  dashboard: "border-l-answer bg-ticket",
  clarify: "border-l-clarify bg-clarify",
  refuse: "border-l-refuse bg-panel",
  error: "border-l-clarify bg-ticket",
  pending: "border-l-channel bg-ticket",
};

interface Props {
  question: string;
  route: TurnRoute;
  children: ReactNode;
}

/** One user question and plumb's response as two visually separate blocks. */
export function TurnExchange({ question, route, children }: Props) {
  return (
    <section
      className="flex flex-col gap-3"
      aria-label="Conversation turn"
      data-testid="turn-exchange"
    >
      <div className="turn-question" data-testid="turn-question">
        <p className="stamp mb-2 text-muted">You asked</p>
        <p className="text-[15px] font-medium leading-6 text-ink">{question}</p>
      </div>
      <div
        className={`turn-response border-l-4 ${RESPONSE_SHELL[route]}`}
        data-testid="turn-response"
        data-route={route}
      >
        {children}
      </div>
    </section>
  );
}
