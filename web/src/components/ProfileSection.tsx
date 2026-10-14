import { Check, Cpu, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { api } from "@/api";
import { useAction } from "@/engine";
import { cn } from "@/lib/utils";
import type { ProfileInfo, ProfilePreview, Profiles } from "@/types";
import { ConfirmDialog } from "./ConfirmDialog";
import { useConfig } from "./config/ConfigContext";
import { MissingModels } from "./config/Stage";
import { SavedMark, useSaved } from "./Saved";
import { SettingsSection } from "./SettingsSection";

/** Model sizes for this computer, as selectable cards; switching asks first and lists what it needs. */
export function ProfileSection() {
  const run = useAction();
  const saved = useSaved();
  const [info, setInfo] = useState<Profiles | null>(null);
  const [pending, setPending] = useState<ProfileInfo | null>(null);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const { info: config } = useConfig();

  useEffect(() => {
    run(api.profiles).then((p) => p && setInfo(p));
  }, []);

  const ask = async (p: ProfileInfo) => {
    if (!info || p.name === info.current || busy) return;
    setPending(p);
    setPreview(null);
    const result = await run(() => api.previewProfile(p.name));
    if (result) setPreview(result);
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    const next = await run(() => api.setProfile(pending.name));
    setBusy(false);
    if (next) {
      setInfo(next);
      saved.flash("profile");
    }
    setPending(null);
  };

  return (
    <SettingsSection
      id="profile"
      title="Profile"
      aside={<SavedMark show={saved.is("profile")} text="Switched" />}
      description={
        <>
          Which models run on this computer. Bigger is more accurate and slower to download. Your own settings in <code>config.toml</code> still
          win.
        </>
      }
    >
      {info ? (
        <div className="py-4">
          <div role="radiogroup" aria-label="Profile" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {info.profiles.map((p) => {
              const current = p.name === info.current;
              return (
                <button
                  key={p.name}
                  type="button"
                  role="radio"
                  aria-checked={current}
                  disabled={busy}
                  onClick={() => ask(p)}
                  className={cn(
                    "relative grid content-start gap-1.5 rounded-2xl border bg-card p-4 text-left transition-[border-color,box-shadow]",
                    current ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/50",
                  )}
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <b className="text-base">{p.title}</b>
                    {p.name === info.recommended && <Badge variant="sky">Recommended</Badge>}
                    {current && <Check className="ml-auto size-4 text-link" aria-hidden="true" />}
                  </span>
                  <span className="text-sm text-muted-foreground">{p.description}</span>
                  <span className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    {p.accelerator === "cpu" ? <Cpu className="size-3.5" /> : <Zap className="size-3.5" />}
                    {p.accelerator === "cpu" ? "CPU" : "Graphics card"} · {p.llm_model ?? "no grammar"}
                  </span>
                </button>
              );
            })}
          </div>
          {info.current === null && (
            <p className="mt-3 mb-0 text-sm text-muted-foreground">No profile chosen yet: the built-in defaults (same as Standard) are in use.</p>
          )}
          <MissingModels names={config.missing_models} />
          {info.needs && info.needs.length > 0 && (
            <div className="mt-4 rounded-xl bg-primary/8 px-4 py-3 text-sm">
              <p className="m-0 font-semibold">Still to do</p>
              <ul className="mt-1 mb-0 pl-5">
                {info.needs.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <p className="py-4 text-muted-foreground">Loading…</p>
      )}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && !busy && setPending(null)}
        title={pending ? `Switch to ${pending.title}?` : ""}
        description={pending?.description}
        confirm={busy ? "Switching…" : "Switch"}
        busy={busy || !preview}
        onConfirm={confirm}
      >
        {preview ? (
          preview.needs.length ? (
            <div className="text-sm">
              <p className="m-0 font-semibold">
                What happens{preview.download_gb ? ` (about ${preview.download_gb.toFixed(1)} GB to download)` : ""}
              </p>
              <ul className="mt-1 mb-0 pl-5 text-muted-foreground">
                {preview.needs.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="m-0 text-sm text-muted-foreground">Everything it needs is already on this computer.</p>
          )
        ) : (
          <p className="m-0 text-sm text-muted-foreground">Checking what it needs…</p>
        )}
      </ConfirmDialog>
    </SettingsSection>
  );
}
