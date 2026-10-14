import { useEffect, useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/api";
import { useAction } from "@/engine";
import type { Device } from "@/types";

const DEFAULT = "__default";

/** Choose the microphone the engine records from (saved in the engine's settings). */
export function MicSelect({ id, onSaved }: { id?: string; onSaved?: () => void }) {
  const run = useAction();
  const [provider, setProvider] = useState("");
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [selected, setSelected] = useState(DEFAULT);

  useEffect(() => {
    run(api.devices).then((d) => {
      if (!d) return;
      setProvider(d.provider);
      setDevices(d.devices);
      setSelected(d.selected ?? DEFAULT);
    });
  }, []);

  const change = async (device: string) => {
    setSelected(device);
    const value = device === DEFAULT ? null : device;
    if (await run(() => api.saveSettings({ capture: { provider, device: value } }))) onSaved?.();
  };

  const defaultName = devices?.find((d) => d.is_default)?.name;
  return (
    <Select value={selected} onValueChange={change} disabled={devices === null}>
      <SelectTrigger id={id} aria-label="Microphone" className="h-10 w-full min-w-0 bg-card sm:w-72">
        <SelectValue placeholder="Loading…" />
      </SelectTrigger>
      <SelectContent position="popper" className="rounded-xl">
        <SelectItem value={DEFAULT}>System default{defaultName ? ` (${defaultName})` : ""}</SelectItem>
        {devices?.map((d) => (
          <SelectItem key={d.id} value={d.id}>
            {d.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
