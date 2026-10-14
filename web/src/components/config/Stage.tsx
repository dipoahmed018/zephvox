import { ArrowDown, ArrowUp, ChevronDown, Download, Plus, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { SettingsSection } from "@/components/SettingsSection";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { cn } from "@/lib/utils";
import type { OptionGroup } from "@/types";
import { useConfig } from "./ConfigContext";
import { Field } from "./Field";

export const DRIVER_NAMES: Record<string, string> = {
  "hf-whisper": "Whisper (GPU or CPU)",
  "faster-whisper": "faster-whisper (fast on the CPU)",
  chain: "Dictionaries, then a model for unknown words",
  cmudict: "CMU dictionary (American)",
  misaki: "misaki dictionaries (US or UK)",
  "deep-phonemizer": "DeepPhonemizer (guesses from spelling)",
  espeak: "eSpeak (plugin)",
  wav2vec2: "wav2vec2 sound recognizer",
  "openai-compat": "Ollama or any OpenAI-compatible API",
  kokoro: "Kokoro (natural voices)",
  "espeak-ng": "eSpeak NG (robotic, very light)",
  pipewire: "PipeWire",
  sounddevice: "PortAudio (sounddevice)",
  portal: "Desktop portal (KDE, GNOME 48+)",
  pynput: "Keyboard listener (X11, Windows, macOS)",
};

/** Options of one driver or check, as rows. */
export function Options({ path, group }: { path: string[]; group: OptionGroup }) {
  return (
    <>
      {group.fields.map((f) => (
        <Field key={f.key} path={[...path, f.key]} spec={f} value={group.values[f.key]} base={group.base[f.key]} />
      ))}
    </>
  );
}

/** The drivers for one job, in order of preference; the first one that can run is used. */
function DriverOrder({ kind }: { kind: string }) {
  const { info, save } = useConfig();
  const stage = info.providers[kind];
  const order = stage.order;
  const byName = Object.fromEntries(stage.drivers.map((d) => [d.name, d]));
  const inUse = order.find((n) => byName[n]?.available);
  const others = stage.drivers.filter((d) => !order.includes(d.name));
  const set = (next: string[]) => save([{ path: ["providers", kind], value: next }]);
  const move = (i: number, by: number) => {
    const next = [...order];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    set(next);
  };
  return (
    <div className="py-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-base font-semibold">Drivers, in order</span>
        {JSON.stringify(order) !== JSON.stringify(stage.base_order) && (
          <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={() => save([{ path: ["providers", kind], reset: true }])}>
            Reset order
          </Button>
        )}
      </div>
      <p className="mt-0 mb-3 text-sm text-muted-foreground">The first one that can run here is used; the others are fallbacks.</p>
      <ol className="m-0 grid list-none gap-1.5 p-0">
        {order.map((name, i) => {
          const d = byName[name];
          return (
            <li key={name} className={cn("flex items-center gap-2 rounded-xl border px-3 py-2", name === inUse ? "border-primary/60 bg-primary/5" : "border-border bg-card")}>
              <span className="w-5 text-center text-sm text-muted-foreground tabular-nums">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{DRIVER_NAMES[name] ?? name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {name}
                  {d && !d.available && ` · ${d.reason}`}
                  {!d && " · not installed"}
                </span>
              </span>
              {name === inUse ? <Badge variant="sky">in use</Badge> : d && !d.available ? <Badge variant="alert">can't run</Badge> : null}
              <Button variant="ghost" size="icon-sm" aria-label={`Move ${name} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                <ArrowUp />
              </Button>
              <Button variant="ghost" size="icon-sm" aria-label={`Move ${name} down`} disabled={i === order.length - 1} onClick={() => move(i, 1)}>
                <ArrowDown />
              </Button>
              <Button variant="ghost" size="icon-sm" aria-label={`Remove ${name}`} onClick={() => set(order.filter((n) => n !== name))}>
                <X />
              </Button>
            </li>
          );
        })}
        {order.length === 0 && <li className="rounded-xl border border-dashed px-3 py-2 text-sm text-muted-foreground">None: this job is turned off.</li>}
      </ol>
      {others.length > 0 && (
        <Select value="" onValueChange={(name) => set([...order, name])}>
          <SelectTrigger className="mt-2 h-9 w-full bg-card sm:w-72" aria-label="Add a driver">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Plus className="size-4" /> Add a driver
            </span>
          </SelectTrigger>
          <SelectContent position="popper" className="rounded-xl">
            {others.map((d) => (
              <SelectItem key={d.name} value={d.name}>
                {DRIVER_NAMES[d.name] ?? d.name}
                {!d.available && " (can't run here)"}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

/** One job (speech to text, grammar…): its drivers and their options. */
export function Stage({ id, kind, title, description, children }: { id: string; kind: string; title: string; description: string; children?: React.ReactNode }) {
  const { info } = useConfig();
  const stage = info.providers[kind];
  if (!stage) return null;
  const inUse = stage.order.find((n) => stage.drivers.find((d) => d.name === n)?.available);
  const listed = stage.order.map((n) => stage.drivers.find((d) => d.name === n)).filter((d) => d && d.fields.length > 0);
  return (
    <SettingsSection id={id} title={title} description={description}>
      {children}
      <DriverOrder kind={kind} />
      {listed.map((d) => (
        <Collapsible key={d!.name} defaultOpen={d!.name === inUse} className="py-2">
          <CollapsibleTrigger className="group flex w-full items-center gap-2 py-2 text-left">
            <span className="flex-1 font-semibold">
              {DRIVER_NAMES[d!.name] ?? d!.name} <span className="font-normal text-muted-foreground">options</span>
            </span>
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent className="divide-y divide-border border-l-2 border-border pl-4">
            <Options path={["provider", d!.name]} group={d!} />
          </CollapsibleContent>
        </Collapsible>
      ))}
    </SettingsSection>
  );
}

/** Grammar models the config uses but that aren't downloaded, with a Download button and progress. */
export function MissingModels({ names }: { names: string[] }) {
  const { state } = useEngine();
  const { info } = useConfig();
  const run = useAction();
  const [started, setStarted] = useState<string[]>([]);
  const shown = names.filter((n) => !(state.downloads[n] ?? info.downloads[n])?.ok);
  if (!shown.length) return null;
  return (
    <div className="my-3 grid gap-2">
      {shown.map((name) => {
        const d = state.downloads[name] ?? info.downloads[name];
        const running = d?.running || (started.includes(name) && !d);
        return (
          <div key={name} className="rounded-xl border border-alert/50 bg-alert/5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="min-w-0 flex-1 text-sm">
                <b>{name}</b> isn't downloaded, so grammar is skipped.
              </span>
              <Button
                size="sm"
                disabled={running}
                onClick={() => {
                  setStarted((s) => [...s, name]);
                  run(() => api.pullModel(name));
                }}
              >
                <Download /> {running ? "Downloading…" : d?.ok === false ? "Try again" : "Download"}
              </Button>
            </div>
            {d && (d.running || d.ok === false) && (
              <div className="mt-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${d.percent ?? 2}%` }} />
                </div>
                <p className="mt-1 mb-0 truncate text-xs text-muted-foreground">{d.line}</p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
