import { Laptop, Server, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import type { RemoteInfo, SyncStatus } from "@/types";
import { ConfirmDialog } from "./ConfirmDialog";
import { SavedMark, useSaved } from "./Saved";
import { SettingRow, SettingsSection } from "./SettingsSection";

function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) headers[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return headers;
}

function syncText(s: SyncStatus): string {
  if (s.offline) return "Server unreachable: recordings wait here and sync when it's back.";
  if (s.storage_full) return "Your space on the server is full: new recordings stay on this computer only.";
  if (s.error) return `Sync problem: ${s.error}`;
  return s.last ? `Last synced at ${new Date(s.last * 1000).toLocaleTimeString()}.` : "Syncing…";
}

function Log({ lines }: { lines: string[] }) {
  return (
    <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-foreground/[0.04] p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
      {lines.slice(-8).join("\n") || "Starting…"}
    </pre>
  );
}

/** Where analysis runs: this computer, or a zephvox server (connect, sync, keys). */
export function EngineSection() {
  const { state } = useEngine();
  const run = useAction();
  const saved = useSaved();
  const [info, setInfo] = useState<RemoteInfo | null>(null);
  const [choice, setChoice] = useState<"local" | "remote" | null>(null);
  const [form, setForm] = useState({ url: "", invite: "", device: "", headers: "" });
  const [busy, setBusy] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  useEffect(() => {
    // Instantly from local state, then again once the server has been asked.
    run(() => api.remote(false)).then((r) => r && setInfo((old) => old ?? r));
    run(() => api.remote(true)).then((r) => r && setInfo(r));
  }, []);
  useEffect(() => {
    if (state.remote) setInfo((old) => ({ ...state.remote!, reachable: old?.reachable ?? null, error: old?.error ?? null, server: old?.server ?? state.remote!.server }));
  }, [state.remote]);
  useEffect(() => {
    if (info && !form.url && info.url) setForm((f) => ({ ...f, url: info.url ?? "" }));
  }, [info]);

  const act = async (fn: () => Promise<RemoteInfo | unknown>, flash?: string) => {
    setBusy(true);
    const result = await run(fn);
    setBusy(false);
    if (result && typeof result === "object" && "mode" in result) {
      setInfo(result as RemoteInfo);
      setChoice(null);
      if (flash) saved.flash(flash);
    }
    return result;
  };

  if (!info) {
    return (
      <SettingsSection id="engine" title="Where analysis runs">
        <p className="py-4 text-muted-foreground">Loading…</p>
      </SettingsSection>
    );
  }

  const install = state.install ?? info.install;
  const selected = choice ?? info.mode;

  const pick = (mode: string) => {
    if (mode !== "local" && mode !== "remote") return; // clicking the selected item again
    setChoice(mode);
    if (mode === info.mode) return;
    if (mode === "local" && info.engine_installed) act(() => api.setRemote({ mode: "local" }), "mode");
    if (mode === "remote" && info.connected) act(() => api.setRemote({ mode: "remote" }), "mode");
  };

  return (
    <SettingsSection
      id="engine"
      title="Where analysis runs"
      description="Recording always happens here. The speech models can run on this computer or on a zephvox server."
    >
      <SettingRow label="Analysis runs on" aside={<SavedMark show={saved.is("mode")} />}>
        <ToggleGroup
          type="single"
          value={selected}
          onValueChange={pick}
          disabled={busy}
          aria-label="Analysis runs on"
          className="rounded-full bg-foreground/[0.05] p-1"
        >
          <ToggleGroupItem value="local" className="h-8 rounded-full px-3.5 data-[state=on]:bg-card data-[state=on]:shadow-soft">
            <Laptop /> This computer
          </ToggleGroupItem>
          <ToggleGroupItem value="remote" className="h-8 rounded-full px-3.5 data-[state=on]:bg-card data-[state=on]:shadow-soft">
            <Server /> A server
          </ToggleGroupItem>
        </ToggleGroup>
      </SettingRow>

      {selected === "local" && info.engine_installed && (
        <p className="m-0 py-4 text-sm text-muted-foreground">The models run on this computer. Nothing you say leaves it, and it works offline.</p>
      )}

      {selected === "local" && !info.engine_installed && (
        <div className="py-4">
          {install.running ? (
            <>
              <p className="m-0 font-semibold">Installing the engine…</p>
              <p className="m-0 text-sm text-muted-foreground">You can keep using the server while it installs.</p>
              <Log lines={install.log} />
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <p className="m-0 font-semibold">The engine isn't installed on this computer</p>
                <Badge variant="muted">a few GB</Badge>
              </div>
              <p className="mt-1 mb-3 text-sm text-muted-foreground">
                Installing downloads PyTorch and the speech models and takes a few minutes. Until it's done, analysis stays on the server.
              </p>
              {install.ok === false && (
                <>
                  <p className="m-0 text-sm text-alert-ink">
                    The install failed. The last lines are below; you can also run <code>zephvox setup --role full</code> in a terminal.
                  </p>
                  <Log lines={install.log} />
                </>
              )}
              <Button className="mt-3" disabled={busy} onClick={() => act(api.installEngine)}>
                Install the engine
              </Button>
            </>
          )}
        </div>
      )}

      {selected === "remote" && info.connected && (
        <>
          <SettingRow
            label={<span className="break-all">{info.url}</span>}
            description={
              <>
                This device: {info.device ?? "unknown"} · account {info.account ?? "unknown"}
                {info.server && (
                  <>
                    <br />
                    zephvox {info.server.version} · checks {info.server.analyzers.join(" and ") || "nothing right now"} · models chosen by the
                    server's admin
                  </>
                )}
              </>
            }
          >
            {info.reachable === false ? <Badge variant="alert">Unreachable</Badge> : <Badge variant="success">Connected</Badge>}
          </SettingRow>
          {(info.insecure || (info.error && info.reachable)) && (
            <div className="flex gap-2 py-3 text-sm text-alert-ink">
              <ShieldAlert className="mt-0.5 size-4 shrink-0" />
              <span>
                {info.insecure
                  ? "This address uses plain http: your key and recordings cross the network unencrypted. Ask for an https address."
                  : info.error}
              </span>
            </div>
          )}
          <SettingRow
            label="Back up history"
            htmlFor="sync"
            aside={<SavedMark show={saved.is("sync")} />}
            description={
              info.sync && (state.sync ?? info.sync_status)
                ? syncText(state.sync ?? info.sync_status!)
                : "Keep your reports on the server too, and see them on your other devices."
            }
          >
            <Switch id="sync" checked={info.sync} disabled={busy} onCheckedChange={(on) => act(() => api.setRemote({ sync: on }), "sync")} />
          </SettingRow>
          <SettingRow label="This device's key" description="Get a new one if you think it leaked. The old key stops working at once." aside={<SavedMark show={saved.is("key")} text="New key saved" />}>
            <Button variant="outline" disabled={busy} onClick={() => act(api.rotateKey, "key")}>
              Get a new key
            </Button>
            <Button variant="ghost" className="text-muted-foreground" disabled={busy} onClick={() => setConfirmDisconnect(true)}>
              Disconnect
            </Button>
          </SettingRow>
          <ConfirmDialog
            open={confirmDisconnect}
            onOpenChange={setConfirmDisconnect}
            title="Disconnect from this server?"
            description="This device's key is forgotten. To connect again you'll need a new invite from the server's admin."
            confirm="Disconnect"
            danger
            busy={busy}
            onConfirm={async () => {
              await act(api.forgetKey);
              setConfirmDisconnect(false);
            }}
          />
        </>
      )}

      {selected === "remote" && !info.connected && (
        <form
          className="grid gap-4 py-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            const headers = parseHeaders(form.headers);
            act(() => api.connect(form.url, form.invite, form.device || "my computer", Object.keys(headers).length ? headers : undefined));
          }}
        >
          <p className="m-0 text-sm text-muted-foreground sm:col-span-2">Ask the server's admin for its address and an invite code.</p>
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="srv-url">Server address</Label>
            <Input id="srv-url" required type="url" placeholder="https://speak.example.com" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} className="h-10 bg-card" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="srv-invite">Invite code</Label>
            <Input id="srv-invite" required placeholder="inv_…" value={form.invite} onChange={(e) => setForm({ ...form, invite: e.target.value })} className="h-10 bg-card" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="srv-device">This device's name</Label>
            <Input id="srv-device" placeholder="my laptop" value={form.device} onChange={(e) => setForm({ ...form, device: e.target.value })} className="h-10 bg-card" />
          </div>
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="srv-headers">
              Extra headers <span className="font-normal text-muted-foreground">(only if a proxy needs them; one “Name: value” per line)</span>
            </Label>
            <Textarea id="srv-headers" rows={2} value={form.headers} onChange={(e) => setForm({ ...form, headers: e.target.value })} className="bg-card" />
          </div>
          <div>
            <Button type="submit" disabled={busy}>
              {busy ? "Connecting…" : "Connect"}
            </Button>
          </div>
        </form>
      )}
    </SettingsSection>
  );
}
