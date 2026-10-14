// Mirrors the Python data model (src/speakcheck/engine/models.py and friends).

export type Span = [number, number];

export interface Finding {
  analyzer: string;
  sentence: string;
  target: string;
  said: string;
  expected: string;
  explanation: string;
  category: string;
  segment_index: number;
  word_span: Span | null;
  time_span: Span | null;
  confidence: number;
  details: Record<string, unknown>;
}

export interface AnalysisResult {
  session_id: string;
  audio_path: string;
  sentences: string[];
  findings: Finding[];
  providers: Record<string, string>;
  analyzers: string[];
  warnings: string[];
  timings: Record<string, number>;
  duration: number;
  created: string;
  sentence_spans: Span[];
}

export type Feedback = Record<string, string>; // finding index → "dismissed"

export interface SessionSummary {
  id: string;
  created: string;
  duration: number;
  counts: Record<string, number>;
  preview: string;
}

export type PhoneStatus = "ok" | "minor" | "wrong" | "missing" | "extra";

export interface Phone {
  expected: string | null;
  heard: string | null;
  status: PhoneStatus;
}

export interface WordScore {
  word: string;
  explanation: string;
  score: number;
  passed: boolean;
  status: "ok" | "no_speech" | "different_word";
  phones: Phone[];
  tip: string;
  accepted: string[];
}

export interface PracticeAttempt {
  target: string;
  score: number;
  passed: boolean;
  words: WordScore[];
  at: string;
  audio: string | null;
  source_session: string | null;
  status: "ok" | "no_speech" | "different_word";
}

export interface PracticeStats {
  target: string;
  attempts: number;
  best: number | null;
  last: number | null;
  passed: boolean;
  history: { score: number; passed: boolean; at: string }[];
}

export interface WeakWord {
  target: string;
  mistakes: number;
  best: number | null;
  attempts: number;
}

export interface Recording {
  mode: "analysis" | "practice";
  path: string;
  session_id: string | null;
  provider: string;
  started: number;
  meta: Record<string, unknown>;
  elapsed?: number;
  level?: number | null;
}

export interface Triggers {
  driver: string | null;
  active: boolean;
  error: string | null;
  description: string;
  bindings: Record<string, string>;
}

export interface ProviderStatus {
  kind: string;
  name: string;
  available: boolean;
  reason: string;
  selected: boolean;
}

export interface Status {
  busy: boolean;
  recording: Recording | null;
  practice_target: { text: string; session_id: string | null } | null;
  triggers: Triggers;
  engine?: EngineMode;
  doctor: {
    system: { gpu: { backend: string; name: string; vram_gb: number } | null; ram_gb: number };
    providers: ProviderStatus[];
    analyzers: string[];
  };
}

export interface Device {
  id: string;
  name: string;
  is_default: boolean;
}

export interface Settings {
  capture: { provider?: string; device?: string | null };
  tts: { provider?: string; voice?: string | null };
  analyzers: string[];
  shortcuts: Record<string, string>;
}

export interface ProfileInfo {
  name: string;
  title: string;
  description: string;
  gpu: boolean;
  llm_model: string | null;
  accelerator: string;
}

export interface Profiles {
  current: string | null;
  recommended: string;
  hardware: string[];
  installed_accelerator: string | null;
  config_path: string;
  profiles: ProfileInfo[];
  needs?: string[]; // after a switch: what still has to happen
}

export interface History {
  sessions: number;
  dismissed: number;
  categories: Record<string, [string, number][]>;
  targets: Record<string, [string, number][]>;
}

export interface EngineMode {
  mode: "local" | "remote";
  url: string | null;
}

export interface InstallProgress {
  running: boolean;
  ok: boolean | null;
  log: string[];
}

export interface RemoteInfo {
  mode: "local" | "remote";
  url: string | null;
  headers: string[];
  sync: boolean;
  connected: boolean;
  device: string | null;
  account: string | null;
  insecure: boolean;
  engine_installed: boolean;
  install: InstallProgress;
  reachable: boolean | null;
  error: string | null;
}
