import { Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { SettingRow } from "@/components/SettingsSection";
import type { ConfigChange, FieldSpec } from "@/types";
import { useConfig } from "./ConfigContext";

const UNITS: [RegExp, string][] = [
  [/_s$/, " (seconds)"],
  [/_hours$/, " (hours)"],
  [/_mb$/, " (MB)"],
  [/_gb$/, " (GB)"],
  [/_minutes$/, " (minutes)"],
];

const LABELS: Record<string, string> = {
  api_key_env: "API key variable",
  base_url: "Server address",
  vad_filter: "Skip silence",
  compute_type: "Precision",
  beam_size: "Search width",
  min_phones: "Shortest word checked (sounds)",
  flag_major_errors: "Always flag clear mistakes",
  accept_non_rhotic: "Accept British r-dropping",
  min_confidence: "Minimum confidence",
  batch_size: "Sentences per request",
  pass_score: "Score to pass",
  different_word_score: "Below this, it's a different word",
  english_only: "English sounds only",
  silver: "Use the larger dictionary",
  autostart: "Start Ollama when needed",
  serve_command: "Command that starts it",
  sentence_split: "Split the transcript into sentences",
  notifications: "Desktop notifications",
  practice_auto_stop_s: "Practice stops after silence",
  practice_max_s: "Longest practice attempt",
  analyzers: "Checks",
  webhook_allow_private: "Allow webhooks to local addresses",
  practice_workers: "Practice threads",
  job_ttl_hours: "Keep finished jobs",
  requests_per_minute: "Requests per minute",
};

export function humanize(key: string): string {
  if (LABELS[key]) return LABELS[key];
  let unit = "";
  let base = key;
  for (const [re, label] of UNITS) {
    if (re.test(base)) {
      base = base.replace(re, "");
      unit = label;
    }
  }
  const words = base.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1) + unit;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Where the value comes from: changed here (with a reset), config.toml, or the profile. */
function Source({ path, spec, base }: { path: string[]; spec: FieldSpec; base: unknown }) {
  const { info, save } = useConfig();
  const key = path.join(".");
  let node = info.overlay;
  for (const p of path) node = node?.[p];
  if (node !== undefined) {
    return (
      <span className="inline-flex items-center gap-1">
        <Badge variant="sky">changed here</Badge>
        <Button
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          aria-label={`Reset ${humanize(spec.key)}`}
          title={`Back to ${JSON.stringify(base)}`}
          onClick={() => save([{ path, reset: true }])}
        >
          <RotateCcw /> Reset
        </Button>
      </span>
    );
  }
  if (info.in_file.includes(key)) return <Badge variant="muted">config.toml</Badge>;
  if (!same(base, spec.default)) return <Badge variant="muted">profile</Badge>;
  return null;
}

/** A free-text value with known good choices: pick one, or type your own. */
function TextControl({ id, value, nullable, options, onCommit }: {
  id: string;
  value: string | null;
  nullable?: boolean;
  options?: { value: string; label: string }[];
  onCommit: (v: string | null) => void;
}) {
  const [text, setText] = useState(value ?? "");
  const [custom, setCustom] = useState(false);
  useEffect(() => setText(value ?? ""), [value]);
  const commit = () => {
    const next = text.trim() === "" && nullable ? null : text.trim();
    if (next !== value) onCommit(next);
  };
  if (options?.length && !custom) {
    const known = options.some((o) => o.value === value);
    return (
      <Select
        value={value ?? "__default"}
        onValueChange={(v) => (v === "__other" ? setCustom(true) : onCommit(v === "__default" ? null : v))}
      >
        <SelectTrigger id={id} className="h-10 w-full min-w-0 bg-card sm:w-72">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" className="max-h-80 rounded-xl">
          {nullable && <SelectItem value="__default">Default</SelectItem>}
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
          {!known && value !== null && <SelectItem value={value}>{value} (your own)</SelectItem>}
          <SelectItem value="__other">Other…</SelectItem>
        </SelectContent>
      </Select>
    );
  }
  return (
    <Input
      id={id}
      value={text}
      autoFocus={custom}
      placeholder={nullable ? "Default" : undefined}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        commit();
        setCustom(false);
      }}
      onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
      className="h-10 w-full min-w-0 bg-card sm:w-72"
    />
  );
}

function NumberControl({ id, value, integer, onCommit }: { id: string; value: number | null; integer: boolean; onCommit: (v: number) => void }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  const [bad, setBad] = useState(false);
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const n = Number(text);
    if (text.trim() === "" || !Number.isFinite(n) || (integer && !Number.isInteger(n))) {
      setBad(true);
      return;
    }
    setBad(false);
    if (n !== value) onCommit(n);
  };
  return (
    <Input
      id={id}
      inputMode={integer ? "numeric" : "decimal"}
      value={text}
      aria-invalid={bad || undefined}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
      className="h-10 w-32 bg-card tabular-nums"
    />
  );
}

function ListControl({ id, value, onCommit }: { id: string; value: string[]; onCommit: (v: string[]) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    const v = text.trim();
    if (v && !value.includes(v)) onCommit([...value, v]);
    setText("");
  };
  return (
    <div className="flex w-full min-w-0 flex-wrap items-center gap-1.5 sm:w-auto sm:max-w-md">
      {value.map((item, i) => (
        <span key={i} className="inline-flex items-center gap-1 rounded-full border border-border bg-card py-0.5 pr-1 pl-2.5 text-sm">
          {item}
          <button type="button" aria-label={`Remove ${item}`} className="rounded-full p-0.5 hover:bg-accent" onClick={() => onCommit(value.filter((_, j) => j !== i))}>
            <X className="size-3.5" />
          </button>
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <Input
          id={id}
          value={text}
          placeholder="Add"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          className="h-8 w-28 bg-card"
        />
        <Button variant="ghost" size="icon-sm" aria-label="Add" onClick={add} disabled={!text.trim()}>
          <Plus />
        </Button>
      </span>
    </div>
  );
}

function DictControl({ id, value, onCommit }: { id: string; value: Record<string, string>; onCommit: (v: Record<string, string>) => void }) {
  const toText = (d: Record<string, string>) => Object.entries(d).map(([k, v]) => `${k}: ${v}`).join("\n");
  const [text, setText] = useState(toText(value));
  useEffect(() => setText(toText(value)), [JSON.stringify(value)]);
  return (
    <Textarea
      id={id}
      rows={2}
      value={text}
      placeholder="Name: value (one per line)"
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const out: Record<string, string> = {};
        for (const line of text.split("\n")) {
          const at = line.indexOf(":");
          if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
        }
        if (!same(out, value)) onCommit(out);
      }}
      className="w-full bg-card font-mono text-sm sm:w-72"
    />
  );
}

/** One option: its label and description, where its value comes from, and the right control. */
export function Field({ path, spec, value, base, label }: { path: string[]; spec: FieldSpec; value: unknown; base: unknown; label?: string }) {
  const { info, save, savedAt } = useConfig();
  const key = path.join(".");
  const id = `opt-${path.join("-")}`;
  const commit = (v: unknown) => save([{ path, value: v } as ConfigChange]);
  const control = (() => {
    switch (spec.type) {
      case "bool":
        return <Switch id={id} checked={Boolean(value)} onCheckedChange={commit} />;
      case "int":
      case "float":
        return <NumberControl id={id} value={value as number | null} integer={spec.type === "int"} onCommit={commit} />;
      case "choice":
        return (
          <Select value={String(value)} onValueChange={commit}>
            <SelectTrigger id={id} className="h-10 w-full min-w-0 bg-card sm:w-60">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper" className="rounded-xl">
              {spec.choices?.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        );
      case "list":
        return <ListControl id={id} value={(value as string[]) ?? []} onCommit={commit} />;
      case "dict":
        return <DictControl id={id} value={(value as Record<string, string>) ?? {}} onCommit={commit} />;
      default:
        return <TextControl id={id} value={(value as string | null) ?? null} nullable={spec.nullable} options={info.suggestions[key]} onCommit={commit} />;
    }
  })();
  return (
    <SettingRow
      label={label ?? humanize(spec.key)}
      htmlFor={spec.type === "list" || spec.type === "dict" ? undefined : id}
      description={info.docs[key] && info.docs[key].charAt(0).toUpperCase() + info.docs[key].slice(1)}
      aside={
        <>
          <Source path={path} spec={spec} base={base} />
          {savedAt === key && <span className="text-xs font-semibold text-success-ink">Saved</span>}
        </>
      }
      stack={spec.type === "list" || spec.type === "dict"}
    >
      {control}
    </SettingRow>
  );
}
