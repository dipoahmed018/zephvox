import { Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction } from "../engine";
import type { ProfilePreview, Profiles } from "../types";
import { SavedMark, useSaved } from "./Saved";

export function ProfileCard() {
  const run = useAction();
  const saved = useSaved();
  const [info, setInfo] = useState<Profiles | null>(null);
  const [pending, setPending] = useState<string | null>(null); // asked to switch, waiting for "Switch"
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    run(api.profiles).then((p) => p && setInfo(p));
  }, []);

  const ask = async (name: string) => {
    if (!info || name === info.current || busy) return;
    setPending(name);
    setPreview(null);
    const p = await run(() => api.previewProfile(name));
    if (p) setPreview(p);
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    const next = await run(() => api.setProfile(pending));
    setBusy(false);
    if (next) {
      setInfo(next);
      saved.flash("profile");
    }
    setPending(null);
  };

  return (
    <div className="card">
      <div className="card-title">
        <Gauge size={18} color="var(--accent)" />
        <h2>Profile</h2>
        <SavedMark show={saved.is("profile")} text="Switched" />
      </div>
      {info ? (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            Model sizes for this computer. Your own settings in <code>config.toml</code> still win.
          </p>
          <div className="profile-list compact" role="radiogroup" aria-label="Profile">
            {info.profiles.map((p) => {
              const current = p.name === info.current;
              return (
                <div key={p.name}>
                  <button type="button" role="radio" aria-checked={current} className="profile-option"
                          disabled={busy} onClick={() => ask(p.name)}>
                    <span className="profile-row">
                      <b>{p.title}</b>
                      {p.name === info.recommended && <span className="chip teal">recommended</span>}
                      <span className="faint profile-meta">
                        {p.llm_model ?? "no grammar"} · {p.accelerator === "cpu" ? "CPU" : "GPU"}
                      </span>
                    </span>
                    {current && <span className="muted">{p.description}</span>}
                  </button>
                  {pending === p.name && (
                    <div className="confirm-panel" role="dialog" aria-label={`Switch to ${p.title}`}>
                      <p style={{ margin: 0 }}>
                        Switch to <b>{p.title}</b>? {p.description}
                      </p>
                      {preview ? (
                        preview.needs.length ? (
                          <ul className="profile-needs">
                            {preview.needs.map((n) => (
                              <li key={n}>{n}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="faint" style={{ margin: 0 }}>Everything it needs is already here.</p>
                        )
                      ) : (
                        <p className="faint" style={{ margin: 0 }}>Checking what it needs…</p>
                      )}
                      <div className="row" style={{ gap: 8 }}>
                        <button className="btn primary small" disabled={busy || !preview} onClick={confirm}>
                          {busy ? "Switching…" : "Switch"}
                        </button>
                        <button className="btn ghost small" disabled={busy} onClick={() => setPending(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {info.current === null && (
            <p className="faint" style={{ marginBottom: 0 }}>
              No profile chosen yet: the built-in defaults (same as Standard) are in use.
            </p>
          )}
          {info.needs && info.needs.length > 0 && (
            <ul className="profile-needs">
              {info.needs.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </div>
  );
}
