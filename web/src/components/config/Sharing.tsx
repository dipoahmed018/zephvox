import { ChevronDown, Copy, KeyRound, Laptop, Network, Plus, RotateCcw, Trash2, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SettingRow, SettingsSection } from "@/components/SettingsSection";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { fmtDate } from "@/format";
import type { Limits, SharedAccount, SharingInfo } from "@/types";
import { useConfig } from "./ConfigContext";
import { Field } from "./Field";

const LIMITS: { key: keyof Limits; label: string; unit: string; integer: boolean }[] = [
  { key: "max_audio_minutes", label: "Longest recording", unit: "minutes", integer: false },
  { key: "max_jobs", label: "Analyses at once", unit: "waiting or running", integer: true },
  { key: "storage_mb", label: "Synced history", unit: "MB", integer: true },
  { key: "requests_per_minute", label: "Requests", unit: "per minute", integer: true },
];

const segment = "h-8 rounded-full px-3.5 data-[state=on]:bg-card data-[state=on]:shadow-soft";

function copy(text: string, done: () => void) {
  navigator.clipboard?.writeText(text).then(done, () => undefined);
}

function CopyLine({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex max-w-full min-w-0 items-center gap-2 rounded-xl bg-foreground/[0.04] py-1.5 pr-1.5 pl-3">
      <code className="min-w-0 flex-1 truncate font-mono text-sm" title={text}>
        {text}
      </code>
      <Button size="sm" variant="ghost" aria-label={label ?? `Copy ${text}`} onClick={() => copy(text, () => setCopied(true))}>
        <Copy /> {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

/** A limit with the default as a placeholder: empty = use the default. */
function LimitInput({ value, placeholder, integer, label, onCommit }: { value?: number; placeholder: number; integer: boolean; label: string; onCommit: (v: number | null) => void }) {
  const [text, setText] = useState(value === undefined ? "" : String(value));
  useEffect(() => setText(value === undefined ? "" : String(value)), [value]);
  const commit = () => {
    if (text.trim() === "") return value !== undefined && onCommit(null);
    const n = Number(text);
    if (Number.isFinite(n) && n > 0 && (!integer || Number.isInteger(n)) && n !== value) onCommit(n);
  };
  return (
    <Input
      aria-label={label}
      inputMode={integer ? "numeric" : "decimal"}
      value={text}
      placeholder={String(placeholder)}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
      className="h-9 w-28 bg-card tabular-nums"
    />
  );
}

function InviteDialog({ invite, url, onClose }: { invite: SharingInfo["invite"]; url: string; onClose: () => void }) {
  if (!invite) return null;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="rounded-[var(--radius-card)] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-xl font-normal">Invite for {invite.account}</DialogTitle>
          <DialogDescription>
            Connects one device, until {fmtDate(new Date(invite.expires * 1000).toISOString())}. It's shown only now: copy it before closing.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-sm">
          <CopyLine text={invite.code} label="Copy the invite code" />
          <p className="m-0 text-muted-foreground">On the other device: Settings → Where analysis runs → A server, with this address and code. Or install it with:</p>
          <CopyLine text={`speakcheck setup --server-url ${url} --invite ${invite.code}`} label="Copy the setup command" />
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Account({ account, defaults, act }: { account: SharedAccount; defaults: Limits; act: (action: string, body: Record<string, unknown>) => Promise<unknown> }) {
  const [days, setDays] = useState("7");
  const [removing, setRemoving] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const devices = account.devices.filter((d) => d.revoked === null);
  return (
    <Collapsible className="py-1">
      <CollapsibleTrigger className="group flex w-full items-center gap-3 py-3 text-left">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary/10 font-semibold text-link uppercase">{account.name.charAt(0)}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{account.name}</span>
          <span className="block text-sm text-muted-foreground">
            {devices.length} device{devices.length === 1 ? "" : "s"} · {account.usage.storage_mb} MB synced
            {account.usage.active_jobs ? ` · ${account.usage.active_jobs} analyzing` : ""}
          </span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mb-3 grid gap-5 rounded-2xl bg-foreground/[0.03] p-4">
        <div>
          <h4 className="eyebrow mt-0 mb-2">Connect a device</h4>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={days} onValueChange={setDays}>
              <SelectTrigger className="h-9 w-40 bg-card" aria-label="Invite valid for">
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper" className="rounded-xl">
                {["1", "7", "30"].map((d) => (
                  <SelectItem key={d} value={d}>
                    Valid {d} day{d === "1" ? "" : "s"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" onClick={() => act("invite", { account: account.id, days: Number(days) })}>
              <Plus /> New invite
            </Button>
          </div>
        </div>
        <div>
          <h4 className="eyebrow mt-0 mb-2">Devices</h4>
          {account.devices.length === 0 ? (
            <p className="m-0 text-sm text-muted-foreground">None yet. Send an invite to connect one.</p>
          ) : (
            <ul className="m-0 grid list-none gap-1.5 p-0">
              {account.devices.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-card px-3 py-2 text-sm">
                  <Laptop className="size-4 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate font-semibold">{d.name}</span>
                  <span className="text-muted-foreground">
                    {d.revoked ? `disconnected ${fmtDate(new Date(d.revoked * 1000).toISOString())}` : d.last_seen ? `seen ${fmtDate(new Date(d.last_seen * 1000).toISOString())}` : "never seen"}
                  </span>
                  {!d.revoked && (
                    <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => act("revoke_device", { device: d.id })}>
                      Disconnect
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="eyebrow mt-0 mb-2">Limits</h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {LIMITS.map((l) => (
              <label key={l.key} className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {l.label} <span className="text-muted-foreground">({l.unit})</span>
                </span>
                <LimitInput
                  label={`${l.label} for ${account.name}`}
                  value={account.overrides[l.key]}
                  placeholder={defaults[l.key]}
                  integer={l.integer}
                  onCommit={(v) => act("set_limits", { account: account.id, changes: { [l.key]: v } })}
                />
              </label>
            ))}
          </div>
          <p className="mt-2 mb-0 text-xs text-muted-foreground">Empty = the default for every account.</p>
        </div>
        <div>
          <h4 className="eyebrow mt-0 mb-2">Webhook secret</h4>
          <p className="mt-0 mb-2 text-sm text-muted-foreground">Signs the job notifications this account's webhooks receive.</p>
          {showSecret ? (
            <CopyLine text={account.webhook_secret} label="Copy the webhook secret" />
          ) : (
            <Button size="sm" variant="outline" onClick={() => setShowSecret(true)}>
              <KeyRound /> Show
            </Button>
          )}
          <Button size="sm" variant="ghost" className="mt-1 text-muted-foreground" onClick={() => act("rotate_secret", { account: account.id })}>
            <RotateCcw /> Make a new one
          </Button>
        </div>
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" className="text-alert-ink" onClick={() => setRemoving(true)}>
            <Trash2 /> Delete account
          </Button>
        </div>
        <ConfirmDialog
          open={removing}
          onOpenChange={setRemoving}
          title={`Delete ${account.name}?`}
          description="Its devices are disconnected, and its jobs and synced history are deleted from this computer. This can't be undone."
          confirm="Delete"
          danger
          onConfirm={async () => {
            await act("remove_account", { account: account.id });
            setRemoving(false);
          }}
        />
      </CollapsibleContent>
    </Collapsible>
  );
}

/** "Share this computer": serve other devices with this computer's models, and manage who may. */
export function Sharing() {
  const { state } = useEngine();
  const run = useAction();
  const { info: config, save } = useConfig();
  const [info, setInfo] = useState<SharingInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [invite, setInvite] = useState<SharingInfo["invite"]>(undefined);
  const [service, setService] = useState<string | null>(null);

  useEffect(() => {
    run(api.sharing).then((s) => s && setInfo(s));
  }, [state.sharingVersion, state.configVersion]);

  if (!info) return <p className="text-muted-foreground">Loading…</p>;

  const act = async (action: string, body: Record<string, unknown>) => {
    const next = await run(() => api.sharingAction(action, body));
    if (next) {
      setInfo(next);
      if (next.invite) setInvite(next.invite);
    }
    return next;
  };
  const toggle = async (on: boolean) => {
    setBusy(true);
    const next = await run(() => api.setSharing(on));
    setBusy(false);
    if (next) setInfo(next);
  };
  const network = config.server.values.host !== "127.0.0.1" && config.server.values.host !== "localhost";
  const address = info.urls[0] ?? `http://${network ? "<this computer>" : "127.0.0.1"}:${config.server.values.port}`;
  const serverFields = config.server.fields.filter((f) => !["share", "host", "port"].includes(f.key));
  const portSpec = config.server.fields.find((f) => f.key === "port");

  return (
    <div className="grid gap-6">
      <SettingsSection
        id="share"
        title="Share this computer"
        description="Let your other devices, or other people, analyze with this computer's models. They connect with an invite, and their recordings and history stay on their own devices."
      >
        <SettingRow
          label="Share"
          htmlFor="share-switch"
          description={info.running ? "Running. It starts again whenever speakcheck does." : info.enabled ? "Turned on, but not running right now." : "Off."}
          aside={info.running ? <Badge variant="success">sharing</Badge> : null}
        >
          <Switch id="share-switch" checked={info.running} disabled={busy || info.remote} onCheckedChange={toggle} />
        </SettingRow>
        {info.remote && <p className="m-0 py-3 text-sm text-alert-ink">This computer itself uses a server for analysis, so it has no engine to share.</p>}
        {info.error && <p className="m-0 py-3 text-sm text-alert-ink">{info.error}</p>}
        {info.running && (
          <div className="grid gap-2 py-4">
            <span className="text-sm font-semibold">Devices connect to</span>
            {info.urls.map((u) => (
              <CopyLine key={u} text={u} />
            ))}
            {network && (
              <p className="m-0 text-xs text-muted-foreground">
                Plain http is fine on your own network. To reach this computer from the internet, put HTTPS in front of it (e.g. Caddy or nginx).
              </p>
            )}
          </div>
        )}
        <SettingRow label="Who can connect" description={network ? "Any device on your network that has an invite." : "Only programs on this computer (for testing, or behind your own proxy)."}>
          <ToggleGroup
            type="single"
            value={network ? "network" : "local"}
            onValueChange={(v) => v && save([{ path: ["server", "host"], value: v === "network" ? "0.0.0.0" : "127.0.0.1" }])}
            aria-label="Who can connect"
            className="rounded-full bg-foreground/[0.05] p-1"
          >
            <ToggleGroupItem value="local" className={segment}>
              <Laptop /> This computer
            </ToggleGroupItem>
            <ToggleGroupItem value="network" className={segment}>
              <Network /> My network
            </ToggleGroupItem>
          </ToggleGroup>
        </SettingRow>
        {portSpec && <Field path={["server", "port"]} spec={portSpec} value={config.server.values.port} base={config.server.base.port} />}
      </SettingsSection>

      <SettingsSection id="accounts" title="Accounts" description="One per person. Each of their devices connects with its own invite and key.">
        <form
          className="flex flex-wrap gap-2 py-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (name.trim() && (await act("add_account", { name: name.trim() }))) setName("");
          }}
        >
          <Input aria-label="New account's name" placeholder="Name, e.g. alice" value={name} onChange={(e) => setName(e.target.value)} className="h-10 max-w-xs bg-card" />
          <Button type="submit" disabled={!name.trim()}>
            <UserPlus /> Add and invite
          </Button>
        </form>
        {info.accounts.length === 0 ? (
          <p className="m-0 py-4 text-sm text-muted-foreground">No accounts yet. Add one to create its first invite.</p>
        ) : (
          info.accounts.map((a) => <Account key={a.id} account={a} defaults={info.defaults.limits} act={act} />)
        )}
      </SettingsSection>

      <SettingsSection id="limits" title="Default limits" description="For every account, unless set for the account itself. Empty = the value from config.toml.">
        <div className="grid gap-3 py-4 sm:grid-cols-2">
          {LIMITS.map((l) => (
            <label key={l.key} className="flex items-center justify-between gap-3 text-sm">
              <span>
                {l.label} <span className="text-muted-foreground">({l.unit})</span>
              </span>
              <LimitInput
                label={`Default ${l.label.toLowerCase()}`}
                value={info.defaults.overrides[l.key]}
                placeholder={info.defaults.config[l.key]}
                integer={l.integer}
                onCommit={(v) => act("set_limits", { account: null, changes: { [l.key]: v } })}
              />
            </label>
          ))}
        </div>
      </SettingsSection>

      <SettingsSection id="jobs" title="Recent analyses" description="Jobs from connected devices and the API. Finished ones are deleted after a while (see below).">
        {info.jobs.length === 0 ? (
          <p className="m-0 py-4 text-sm text-muted-foreground">None yet.</p>
        ) : (
          <ul className="m-0 list-none p-0">
            {info.jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-sm">
                <span className="w-32 shrink-0 text-muted-foreground">{fmtDate(new Date(j.created * 1000).toISOString())}</span>
                <span className="min-w-0 flex-1 truncate font-semibold">{j.account}</span>
                <span className="text-muted-foreground tabular-nums">{j.duration ? `${(j.duration / 60).toFixed(1)} min` : ""}</span>
                <Badge variant={j.status === "done" ? "success" : j.status === "failed" ? "alert" : j.status === "running" ? "sky" : "muted"} title={j.error ?? undefined}>
                  {j.status}
                </Badge>
                {(j.status === "queued" || j.status === "running") && (
                  <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => act("cancel_job", { job: j.id })}>
                    Cancel
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SettingsSection>

      <SettingsSection id="server-options" title="Server options">
        {serverFields.map((f) => (
          <Field key={f.key} path={["server", f.key]} spec={f} value={config.server.values[f.key]} base={config.server.base[f.key]} />
        ))}
        <Collapsible className="py-3">
          <CollapsibleTrigger className="group flex w-full items-center gap-2 py-1 text-left font-semibold">
            <span className="flex-1">Run the server without the app</span>
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <p className="mt-2 mb-3 text-sm text-muted-foreground">
              A background service that starts with the computer, even when speakcheck isn't open (a systemd user unit on Linux, a LaunchAgent on
              macOS, a scheduled task on Windows). It loads its own copy of the models and uses the same port, so turn Share off first.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" disabled={info.running} onClick={() => run(() => api.sharingService("install")).then((r) => r && setService(`Installed: ${r.service}`))}>
                Install the service
              </Button>
              <Button size="sm" variant="ghost" onClick={() => run(() => api.sharingService("remove")).then((r) => r && setService(r.service === "none" ? "No service was installed." : "Removed."))}>
                Remove it
              </Button>
              {service && <span className="text-sm text-muted-foreground">{service}</span>}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </SettingsSection>

      <InviteDialog invite={invite} url={address} onClose={() => setInvite(undefined)} />
    </div>
  );
}
