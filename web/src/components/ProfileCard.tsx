import { Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction } from "../engine";
import type { Profiles } from "../types";

export function ProfileCard() {
  const run = useAction();
  const [info, setInfo] = useState<Profiles | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    run(api.profiles).then((p) => p && setInfo(p));
  }, []);

  const choose = async (name: string) => {
    if (!info || name === info.current || saving) return;
    setSaving(name);
    const next = await run(() => api.setProfile(name));
    setSaving(null);
    if (next) setInfo(next);
  };

  return (
    <div className="card">
      <div className="card-title">
        <Gauge size={18} color="var(--accent)" />
        <h2>Profile</h2>
      </div>
      {info ? (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            Model sizes for this computer. Your own settings in <code>config.toml</code> still win.
          </p>
          <div className="profile-list" role="radiogroup" aria-label="Profile">
            {info.profiles.map((p) => (
              <button
                key={p.name}
                type="button"
                role="radio"
                aria-checked={p.name === info.current}
                className="profile-option"
                disabled={saving !== null}
                onClick={() => choose(p.name)}
              >
                <span className="row" style={{ gap: 8 }}>
                  <b>{p.title}</b>
                  {p.name === info.recommended && <span className="chip teal">recommended</span>}
                  {saving === p.name && <span className="faint">switching…</span>}
                </span>
                <span className="muted">{p.description}</span>
                <span className="faint">Grammar: {p.llm_model ?? "off"} · PyTorch: {p.accelerator}</span>
              </button>
            ))}
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
