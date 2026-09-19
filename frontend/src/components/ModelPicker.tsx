import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import type { ModelCatalog } from "../types";
import { ApiRequestError } from "../types";

interface Props {
  disabled?: boolean;
  sessionId: string | null;
}

interface CustomDraft {
  url: string;
  key: string;
  model: string;
}

function humanizeError(message: string): string {
  if (/^no session/i.test(message)) {
    return "Session expired. Reload or start a new session.";
  }
  if (message.length > 72) {
    return "Could not load models for this session.";
  }
  return message;
}

export function ModelPicker({ disabled, sessionId }: Props) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<CustomDraft>({ url: "", key: "", model: "" });
  const [tested, setTested] = useState(false);
  const [testing, setTesting] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .models(sessionId)
      .then((next) => {
        if (cancelled) return;
        setCatalog(next);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiRequestError ? err.message : String(err);
        setError(humanizeError(message));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function remember(next: ModelCatalog) {
    setCatalog(next);
    setError(null);
    setOpen(false);
    setTested(false);
  }

  async function apply(provider: string, model: string) {
    try {
      remember(await api.setModel(provider, model, sessionId));
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setError(humanizeError(message));
    }
  }

  async function testCustom() {
    if (!sessionId) {
      setError("Upload a spreadsheet first.");
      return;
    }
    setTesting(true);
    try {
      await api.testEndpoint(sessionId, draft);
      setTested(true);
      setError(null);
    } catch (err) {
      setTested(false);
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setError(humanizeError(message));
    } finally {
      setTesting(false);
    }
  }

  async function saveCustom() {
    if (!sessionId || !tested) return;
    try {
      remember(
        await api.setSessionProvider(sessionId, {
          provider: "custom",
          model: draft.model,
          url: draft.url,
          key: draft.key || undefined,
        }),
      );
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : String(err);
      setError(humanizeError(message));
    }
  }

  if (!catalog) {
    return (
      <div className="model-picker">
        <div className="model-picker__controls is-disabled">
          <span className="model-picker__field stamp text-muted">
            {error ?? "Loading models…"}
          </span>
        </div>
      </div>
    );
  }

  const selected =
    catalog.providers.find((item) => item.id === catalog.provider) ?? catalog.providers[0];
  const models = selected?.models ?? [];
  const isCustom = catalog.provider === "custom" || open;
  const currentModel =
    models.find((item) => item.id === catalog.model)?.label ?? catalog.model;

  return (
    <div className="model-picker relative" ref={box}>
      <div
        className={[
          "model-picker__controls",
          disabled ? "is-disabled" : "",
        ].join(" ")}
        title={error ?? `${selected?.label ?? catalog.provider} · ${currentModel}`}
      >
        <label className="model-picker__field">
          <span className="stamp hidden text-muted sm:inline">Platform</span>
          <select
            className="dial"
            value={open ? "custom" : catalog.provider}
            disabled={disabled}
            aria-label="LLM platform"
            onChange={(event) => {
              const id = event.target.value;
              if (id === "custom") {
                setOpen(true);
                setTested(false);
                setDraft((prev) => ({
                  url: prev.url,
                  key: prev.key,
                  model: prev.model || catalog.model,
                }));
                return;
              }
              const next = catalog.providers.find((item) => item.id === id);
              const fallback = next?.models[0]?.id ?? catalog.model;
              void apply(id, fallback);
            }}
          >
            {catalog.providers.map((item) => (
              <option
                key={item.id}
                value={item.id}
                disabled={(item.id === "custom" || item.kind === "preset") && !sessionId}
              >
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {catalog.provider === "custom" ? (
          <button
            type="button"
            className="model-picker__field stamp text-muted hover:text-ink"
            disabled={disabled}
            onClick={() => setOpen((value) => !value)}
          >
            {catalog.host ?? "endpoint"}
          </button>
        ) : (
          <label className="model-picker__field">
            <span className="stamp hidden text-muted sm:inline">Model</span>
            <select
              className="dial model-picker__model"
              value={catalog.model}
              disabled={disabled}
              aria-label="LLM model"
              title={currentModel}
              onChange={(event) => void apply(catalog.provider, event.target.value)}
            >
              {models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {error ? (
        <p className="w-full text-right font-mono text-[10px] leading-snug text-clarify sm:max-w-[20rem]">
          {error}
        </p>
      ) : null}
      {isCustom && open ? (
        <div className="picker-pop">
          <label className="block">
            <span className="stamp text-muted">URL</span>
            <input
              className="mt-1 w-full border border-line bg-panel px-2 py-1 font-mono text-[11px] text-ink"
              value={draft.url}
              placeholder="http://localhost:11434/v1/chat/completions"
              autoComplete="off"
              onChange={(event) => {
                setDraft({ ...draft, url: event.target.value });
                setTested(false);
              }}
            />
          </label>
          <label className="mt-2 block">
            <span className="stamp text-muted">Key</span>
            <input
              className="mt-1 w-full border border-line bg-panel px-2 py-1 font-mono text-[11px] text-ink"
              type="password"
              value={draft.key}
              placeholder="optional"
              autoComplete="off"
              onChange={(event) => {
                setDraft({ ...draft, key: event.target.value });
                setTested(false);
              }}
            />
          </label>
          <label className="mt-2 block">
            <span className="stamp text-muted">Model</span>
            <input
              className="mt-1 w-full border border-line bg-panel px-2 py-1 font-mono text-[11px] text-ink"
              value={draft.model}
              placeholder="llama3.2"
              autoComplete="off"
              onChange={(event) => {
                setDraft({ ...draft, model: event.target.value });
                setTested(false);
              }}
            />
          </label>
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              className="border border-line px-2 py-1 stamp text-muted hover:text-ink"
              disabled={disabled || testing || !draft.url || !draft.model}
              onClick={() => void testCustom()}
            >
              {testing ? "Testing" : "Test connection"}
            </button>
            <button
              type="button"
              className="bg-ink px-2 py-1 stamp text-ticket disabled:opacity-40"
              disabled={disabled || !tested}
              onClick={() => void saveCustom()}
            >
              Save
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
