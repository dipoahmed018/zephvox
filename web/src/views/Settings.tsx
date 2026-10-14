import { ChevronDown, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { AnalyzerToggles } from "@/components/AnalyzerToggles";
import { EngineSection } from "@/components/EngineSection";
import { MicSelect } from "@/components/MicSelect";
import { PageHead } from "@/components/PageHead";
import { ProfileSection } from "@/components/ProfileSection";
import { SavedMark, useSaved } from "@/components/Saved";
import { SettingRow, SettingsSection } from "@/components/SettingsSection";
import { Keys } from "@/components/Shortcut";
import { VoiceSelect } from "@/components/VoiceSelect";
import { LICENSE_NAME, SOURCE_URL } from "@/about";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { setTheme, useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import type { ServerInfo, Status } from "@/types";

const ACTIONS: Record<string, { label: string; description: string }> = {
  toggle_recording: { label: "Start or stop recording", description: "Works while another app is in front." },
  practice_attempt: { label: "Practice attempt", description: "Records one try at the current practice word." },
  cancel: { label: "Cancel", description: "Throws away the recording in progress." },
};

const KINDS: Record<string, string> = {
  capture: "Microphone",
  stt: "Speech to text",
  g2p: "Expected sounds",
  phonemes: "Heard sounds",
  llm: "Grammar model",
  tts: "Reference voice",
  triggers: "Shortcuts",
};

function LocalBadge({ show }: { show: boolean }) {
  return show ? <Badge variant="muted">on this computer</Badge> : null;
}

const segment = "h-8 rounded-full px-3.5 data-[state=on]:bg-card data-[state=on]:shadow-soft";

export function Settings() {
  const { state } = useEngine();
  const run = useAction();
  const saved = useSaved();
  const theme = useTheme();
  const [status, setStatus] = useState<Status | null>(null);
  const [analyzers, setAnalyzers] = useState<string[]>([]);
  const [server, setServer] = useState<ServerInfo | null>(null);
  const remote = state.engineMode?.mode === "remote";

  useEffect(() => {
    run(api.status).then((s) => s && setStatus(s));
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, []);
  // In client mode, offer only the checks the server can run.
  useEffect(() => {
    if (remote) run(() => api.remote(true)).then((r) => r && setServer(r.server));
    else setServer(null);
  }, [remote]);

  const triggers = state.triggers ?? status?.triggers;
  const hw = status?.hardware;
  // In client mode the server does the analysis: only this computer's own drivers matter.
  const kinds = remote ? ["capture", "triggers"] : Object.keys(KINDS);
  const sections = [
    ["recording", "Recording"],
    ["shortcuts", "Shortcuts"],
    ["engine", "Analysis"],
    ...(remote ? [] : [["profile", "Profile"]]),
    ["appearance", "Appearance"],
    ["diagnostics", "Diagnostics"],
  ];

  return (
    <>
      <PageHead title="Settings">
        {remote ? "This computer records; a speakcheck server does the analysis." : "Recording, models, and where analysis runs."} Changes are saved as
        you make them.
      </PageHead>

      <nav aria-label="Settings sections" className="mb-6 flex flex-wrap gap-2">
        {sections.map(([id, label]) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
          >
            {label}
          </a>
        ))}
      </nav>

      <div className="grid gap-6">
        <SettingsSection id="recording" title="Recording" aside={<LocalBadge show={remote} />}>
          <SettingRow label="Microphone" htmlFor="mic" description="Used for recordings and practice." aside={<SavedMark show={saved.is("mic")} />}>
            <MicSelect id="mic" onSaved={() => saved.flash("mic")} />
          </SettingRow>
          <SettingRow
            label="Reference voice"
            htmlFor="voice"
            description="The voice that says words back to you."
            aside={<SavedMark show={saved.is("voice")} />}
          >
            <VoiceSelect id="voice" onSaved={() => saved.flash("voice")} />
          </SettingRow>
          <AnalyzerToggles
            value={analyzers}
            available={remote && server ? server.analyzers : undefined}
            savedMark={<SavedMark show={saved.is("analyzers")} />}
            onChange={async (next) => {
              setAnalyzers(next);
              if (await run(() => api.saveSettings({ analyzers: next }))) saved.flash("analyzers");
            }}
          />
        </SettingsSection>

        <SettingsSection
          id="shortcuts"
          title="Shortcuts"
          aside={
            triggers?.active ? (
              <Badge variant="success">Active via {triggers.driver}</Badge>
            ) : triggers?.error ? (
              <Badge variant="alert">Not active</Badge>
            ) : (
              <LocalBadge show={remote} />
            )
          }
          description={triggers?.active ? triggers.description : undefined}
        >
          {triggers ? (
            <>
              {Object.entries(triggers.bindings ?? {}).map(([action, combo]) => (
                <SettingRow key={action} label={ACTIONS[action]?.label ?? action} description={ACTIONS[action]?.description}>
                  <Keys combo={combo} className={cn(!triggers.active && "opacity-50")} />
                </SettingRow>
              ))}
              {!triggers.active && (
                <p className="m-0 py-4 text-sm text-muted-foreground">
                  {triggers.error ? <span className="text-alert-ink">{triggers.error}. </span> : "Registering shortcuts… "}
                  You can still bind <code>speakcheck toggle</code> and <code>speakcheck practice</code> in your system's keyboard settings.
                </p>
              )}
            </>
          ) : (
            <p className="py-4 text-muted-foreground">Loading…</p>
          )}
        </SettingsSection>

        <EngineSection />
        {!remote && <ProfileSection />}

        <SettingsSection id="appearance" title="Appearance">
          <SettingRow label="Theme" description="Light is the default. System follows your computer's setting.">
            <ToggleGroup
              type="single"
              value={theme.choice}
              onValueChange={(v) => v && setTheme(v as ThemeChoice)}
              aria-label="Theme"
              className="rounded-full bg-foreground/[0.05] p-1"
            >
              <ToggleGroupItem value="light" className={segment}>
                <Sun /> Light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark" className={segment}>
                <Moon /> Dark
              </ToggleGroupItem>
              <ToggleGroupItem value="system" className={segment}>
                <Monitor /> System
              </ToggleGroupItem>
            </ToggleGroup>
          </SettingRow>
        </SettingsSection>

        <Collapsible id="diagnostics" className="surface scroll-mt-24 p-5 sm:p-6">
          <CollapsibleTrigger className="group flex w-full items-center gap-3 text-left">
            <span className="flex-1">
              <span className="block font-display text-xl">Diagnostics</span>
              <span className="block text-sm text-muted-foreground">
                {remote ? "Drivers on this computer." : hw?.gpu ? `${hw.gpu.name} · drivers and hardware` : "Hardware and drivers."}
              </span>
            </span>
            <ChevronDown className="size-5 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-5 grid gap-8 md:grid-cols-2">
              {!remote && (
                <div>
                  <h3 className="eyebrow mt-0 mb-3">Hardware</h3>
                  <dl className="m-0 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                    <dt className="text-muted-foreground">Graphics card</dt>
                    <dd className="m-0">
                      {hw
                        ? hw.gpu
                          ? `${hw.gpu.name}${hw.gpu.vram_gb ? `, ${hw.gpu.vram_gb.toFixed(0)} GB` : ""}` +
                            (hw.gpu.backend ? ` (${hw.gpu.backend.toUpperCase()})` : " (not usable for the models here)")
                          : "None: models run on the processor"
                        : "…"}
                    </dd>
                    <dt className="text-muted-foreground">Processor</dt>
                    <dd className="m-0">{hw ? `${hw.cpu} (${hw.cores} threads)` : "…"}</dd>
                    <dt className="text-muted-foreground">Memory</dt>
                    <dd className="m-0">{hw ? `${hw.ram_gb.toFixed(0)} GB` : "…"}</dd>
                  </dl>
                  {hw?.notes.map((n) => (
                    <p key={n} className="mt-3 mb-0 text-sm text-alert-ink">
                      {n}
                    </p>
                  ))}
                </div>
              )}
              <div>
                <h3 className="eyebrow mt-0 mb-3">Drivers</h3>
                {status ? (
                  <dl className="m-0 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-sm">
                    {kinds.map((kind) => (
                      <div key={kind} className="contents">
                        <dt className="text-muted-foreground">{KINDS[kind]}</dt>
                        <dd className="m-0 flex flex-wrap gap-1.5">
                          {status.doctor.providers
                            .filter((p) => p.kind === kind)
                            .map((d) => (
                              <Badge
                                key={d.name}
                                variant={d.selected ? "sky" : d.available ? "muted" : "alert"}
                                title={d.reason || (d.selected ? "in use" : "available")}
                              >
                                {d.selected ? "★ " : d.available ? "" : "✗ "}
                                {d.name}
                              </Badge>
                            ))}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="m-0 text-sm text-muted-foreground">Checking drivers…</p>
                )}
                <p className="mt-3 mb-0 text-xs text-muted-foreground">
                  ★ in use · ✗ unavailable (hover for why).{" "}
                  {remote
                    ? "Speech recognition, sounds, grammar and voices run on the server."
                    : <>Change drivers in <code>config.toml</code> in the speakcheck folder (see <code>config.example.toml</code>).</>}
                </p>
              </div>
            </div>
            <p className="mt-6 mb-0 text-xs text-muted-foreground">
              speakcheck is free software under the {LICENSE_NAME} license:{" "}
              <a href={SOURCE_URL} target="_blank" rel="noreferrer" className="text-link underline underline-offset-2">
                source code
              </a>
              .
            </p>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </>
  );
}
