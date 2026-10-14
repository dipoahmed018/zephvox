import { Laptop, Server } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction, useEngine } from "../engine";
import type { RemoteInfo } from "../types";

function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) headers[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return headers;
}

export function EngineCard() {
  const { state } = useEngine();
  const run = useAction();
  const [info, setInfo] = useState<RemoteInfo | null>(null);
  const [choice, setChoice] = useState<"local" | "remote" | null>(null);
  const [form, setForm] = useState({ url: "", invite: "", device: "", headers: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Instantly from local state, then again once the server has been asked.
    run(() => api.remote(false)).then((r) => r && setInfo((old) => old ?? r));
    run(() => api.remote(true)).then((r) => r && setInfo(r));
  }, []);
  useEffect(() => {
    if (state.remote) setInfo((old) => ({ ...state.remote!, reachable: old?.reachable ?? null, error: old?.error ?? null }));
  }, [state.remote]);
  useEffect(() => {
    if (info && !form.url && info.url) setForm((f) => ({ ...f, url: info.url ?? "" }));
  }, [info]);

  if (!info) {
    return (
      <div className="card">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const install = state.install ?? info.install;
  const selected = choice ?? info.mode;
  const act = async (fn: () => Promise<RemoteInfo | unknown>) => {
    setBusy(true);
    const result = await run(fn);
    setBusy(false);
    if (result && typeof result === "object" && "mode" in result) {
      setInfo(result as RemoteInfo);
      setChoice(null);
    }
  };

  const pick = (mode: "local" | "remote") => {
    setChoice(mode);
    if (mode === info.mode) return;
    if (mode === "local" && info.engine_installed) act(() => api.setRemote({ mode: "local" }));
    if (mode === "remote" && info.connected) act(() => api.setRemote({ mode: "remote" }));
  };

  return (
    <div className="card">
      <div className="card-title">
        <Server size={18} color="var(--accent)" />
        <h2>Where analysis runs</h2>
      </div>
      <div className="profile-list" role="radiogroup" aria-label="Where analysis runs">
        <button type="button" role="radio" aria-checked={selected === "local"} className="profile-option"
                disabled={busy} onClick={() => pick("local")}>
          <span className="row" style={{ gap: 8 }}>
            <Laptop size={16} /> <b>This computer</b>
            {!info.engine_installed && <span className="chip amber">not installed</span>}
          </span>
          <span className="muted">Models run here. Works offline.</span>
        </button>
        <button type="button" role="radio" aria-checked={selected === "remote"} className="profile-option"
                disabled={busy} onClick={() => pick("remote")}>
          <span className="row" style={{ gap: 8 }}>
            <Server size={16} /> <b>A speakcheck server</b>
            {info.connected && <span className="chip teal">connected</span>}
          </span>
          <span className="muted">Record here, analyze on the server. Needs an invite from its admin.</span>
        </button>
      </div>

      {selected === "local" && !info.engine_installed && (
        <div className="engine-panel">
          {install.running ? (
            <>
              <p style={{ marginTop: 0 }}>Installing the engine… you can keep using the server meanwhile.</p>
              <pre className="install-log">{install.log.slice(-8).join("\n")}</pre>
            </>
          ) : (
            <>
              <p style={{ marginTop: 0 }}>
                The engine isn't installed on this computer. Installing it downloads PyTorch and the speech models
                (several GB) and takes a few minutes.
              </p>
              {install.ok === false && (
                <p className="error-text">
                  The install failed. The last lines are below; you can also run <code>speakcheck setup --role full</code> in a
                  terminal.
                </p>
              )}
              {install.ok === false && <pre className="install-log">{install.log.slice(-8).join("\n")}</pre>}
              <button className="btn primary" disabled={busy} onClick={() => act(api.installEngine)}>
                Install now
              </button>
            </>
          )}
        </div>
      )}

      {selected === "remote" && info.connected && (
        <div className="engine-panel">
          <p style={{ marginTop: 0 }}>
            <b>{info.url}</b>
            <br />
            <span className="muted">
              This device: {info.device ?? "?"} · account {info.account ?? "?"}
            </span>
          </p>
          {info.reachable === false && <p className="error-text">The server can't be reached right now.</p>}
          {info.error && info.reachable && <p className="error-text">{info.error}</p>}
          {info.insecure && (
            <p className="error-text">
              This address uses plain http: your key and recordings cross the network unencrypted. Ask for an https address.
            </p>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", margin: "8px 0 12px" }}>
            <input type="checkbox" checked={info.sync} disabled={busy}
                   onChange={(e) => act(() => api.setRemote({ sync: e.target.checked }))} />
            Back up history to the server (and see it on your other devices)
          </label>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn small" disabled={busy} onClick={() => act(api.rotateKey)}
                    title="The old key stops working at once">
              Get a new key
            </button>
            <button className="btn small ghost" disabled={busy}
                    onClick={() => confirm("Disconnect this device from the server?") && act(api.forgetKey)}>
              Disconnect
            </button>
          </div>
        </div>
      )}

      {selected === "remote" && !info.connected && (
        <form className="engine-panel engine-form"
              onSubmit={(e) => {
                e.preventDefault();
                const headers = parseHeaders(form.headers);
                act(() => api.connect(form.url, form.invite, form.device || "my computer",
                                      Object.keys(headers).length ? headers : undefined));
              }}>
          <label>
            Server address
            <input className="input" required placeholder="https://speak.example.com" value={form.url}
                   onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </label>
          <label>
            Invite code
            <input className="input" required placeholder="inv_…" value={form.invite}
                   onChange={(e) => setForm({ ...form, invite: e.target.value })} />
          </label>
          <label>
            This device's name
            <input className="input" placeholder="my laptop" value={form.device}
                   onChange={(e) => setForm({ ...form, device: e.target.value })} />
          </label>
          <label>
            Extra headers <span className="faint">(only if a proxy needs them; one "Name: value" per line)</span>
            <textarea className="input" rows={2} value={form.headers}
                      onChange={(e) => setForm({ ...form, headers: e.target.value })} />
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Connecting…" : "Connect"}
          </button>
        </form>
      )}
    </div>
  );
}
