import type { AskResponse } from "../types";

interface Props {
  response: AskResponse;
}

/**
 * The lightest of the four outcomes: no border accent, no SQL, no chart.
 * A chat reply is not backed by a query, so it must not borrow the visual
 * authority of a card that is.
 */
export function ChatCard({ response }: Props) {
  return (
    <p className="max-w-[65ch] text-[14px] leading-6 text-ink">
      {response.reply}
    </p>
  );
}
