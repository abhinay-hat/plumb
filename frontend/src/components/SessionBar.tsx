import { ModelPicker } from "./ModelPicker";

interface Props {
  sessionId: string | null;
  busy: boolean;
  disabled?: boolean;
  onAudit: () => void;
  onNewSession: () => void;
}

const actionClass =
  "h-8 shrink-0 border border-line bg-ticket px-2.5 stamp text-muted hover:border-ink hover:text-ink disabled:opacity-40";

export function SessionBar({
  sessionId,
  busy,
  disabled,
  onAudit,
  onNewSession,
}: Props) {
  const locked = busy || !sessionId;

  return (
    <div className="session-toolbar">
      <div className="session-toolbar__actions">
        <button
          type="button"
          disabled={locked}
          onClick={onAudit}
          className={`${actionClass} hidden sm:inline`}
        >
          Audit
        </button>
        <button
          type="button"
          disabled={locked}
          onClick={onNewSession}
          className={actionClass}
        >
          New session
        </button>
      </div>
      <ModelPicker sessionId={sessionId} disabled={disabled ?? locked} />
    </div>
  );
}
