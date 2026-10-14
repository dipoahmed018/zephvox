import { Mic } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction } from "../engine";
import type { Device } from "../types";

/** Choose the microphone the engine records from (saved in the engine's settings). */
export function MicSelect() {
  const run = useAction();
  const [provider, setProvider] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    run(api.devices).then((d) => {
      if (!d) return;
      setProvider(d.provider);
      setDevices(d.devices);
      setSelected(d.selected ?? "");
    });
  }, []);

  const change = async (device: string) => {
    setSelected(device);
    await run(() => api.saveSettings({ capture: { provider, device: device || null } }));
  };

  const defaultName = devices.find((d) => d.is_default)?.name;
  return (
    <label className="row" style={{ gap: 8 }}>
      <Mic size={16} className="muted" />
      <span className="visually-hidden">Microphone</span>
      <select value={selected} onChange={(e) => change(e.target.value)} aria-label="Microphone">
        <option value="">System default{defaultName ? ` (${defaultName})` : ""}</option>
        {devices.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </label>
  );
}
