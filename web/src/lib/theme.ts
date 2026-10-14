// Light, dark or follow the system. Light is the default (Breeze is designed light-first).
import { useEffect, useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "speakcheck.theme";
const listeners = new Set<() => void>();
const media = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : undefined;

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "system" ? v : "light";
  } catch {
    return "light";
  }
}

let current: ThemeChoice = typeof window !== "undefined" ? read() : "light";

export function resolvedDark(choice: ThemeChoice = current): boolean {
  return choice === "dark" || (choice === "system" && Boolean(media?.matches));
}

export function applyTheme(choice: ThemeChoice = current): void {
  document.documentElement.classList.toggle("dark", resolvedDark(choice));
}

export function setTheme(choice: ThemeChoice): void {
  current = choice;
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* private window: the choice lasts for this visit */
  }
  applyTheme(choice);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The chosen theme, and whether it currently renders dark. */
export function useTheme(): { choice: ThemeChoice; dark: boolean } {
  const choice = useSyncExternalStore(subscribe, () => current);
  useEffect(() => {
    if (choice !== "system" || !media) return;
    const onChange = () => {
      applyTheme();
      listeners.forEach((l) => l());
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);
  return { choice, dark: resolvedDark(choice) };
}
