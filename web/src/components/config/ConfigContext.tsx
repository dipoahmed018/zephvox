import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import type { ConfigChange, ConfigInfo } from "@/types";

interface Ctx {
  info: ConfigInfo;
  /** Save changes; true when the engine accepted them (otherwise the error is shown as a notice). */
  save: (changes: ConfigChange[]) => Promise<boolean>;
  /** The option just saved ("provider.kokoro.voice"), for a moment, to confirm it. */
  savedAt: string | null;
}

const ConfigContext = createContext<Ctx | null>(null);

/** Loads every option once for the Settings page and keeps it fresh when it changes elsewhere. */
export function ConfigProvider({ children, fallback }: { children: (info: ConfigInfo) => ReactNode; fallback: ReactNode }) {
  const { state } = useEngine();
  const run = useAction();
  const [info, setInfo] = useState<ConfigInfo | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const saving = useRef(false);

  useEffect(() => {
    if (saving.current) return; // our own save already returned the new state
    run(api.config).then((c) => c && setInfo(c));
  }, [state.configVersion]);

  const save = async (changes: ConfigChange[]) => {
    saving.current = true;
    const next = await run(() => api.saveConfig(changes));
    window.setTimeout(() => (saving.current = false), 300);
    if (!next) {
      run(api.config).then((c) => c && setInfo(c)); // show the values as they really are
      return false;
    }
    setInfo(next);
    setSavedAt(changes.length === 1 ? changes[0].path.join(".") : null);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setSavedAt(null), 2000);
    return true;
  };

  if (!info) return <>{fallback}</>;
  return <ConfigContext.Provider value={{ info, save, savedAt }}>{children(info)}</ConfigContext.Provider>;
}

export function useConfig(): Ctx {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfig must be used inside <ConfigProvider>");
  return ctx;
}
