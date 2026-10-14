import { Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, speak } from "../api";
import { useAction } from "../engine";

interface Voice {
  id: string;
  label: string;
}

/** Choose the reference voice used for "Hear it correctly" (saved in the engine's settings). */
export function VoiceSelect() {
  const run = useAction();
  const [provider, setProvider] = useState("");
  const [voices, setVoices] = useState<Voice[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    run(api.voices).then((v) => {
      if (!v) return;
      setProvider(v.provider);
      setVoices(v.voices);
      setSelected(v.selected ?? "");
    });
  }, []);

  if (!voices.length) return <span className="muted">{provider ? `${provider} (one voice)` : "…"}</span>;

  const change = async (voice: string) => {
    setSelected(voice);
    await run(() => api.saveSettings({ tts: { provider, voice } }));
    speak("Think about it.");
  };

  return (
    <span className="row" style={{ gap: 8 }}>
      <select value={selected} onChange={(e) => change(e.target.value)} aria-label="Reference voice">
        {voices.map((v) => (
          <option key={v.id} value={v.id}>
            {v.label}
          </option>
        ))}
      </select>
      <button className="btn ghost small" onClick={() => speak("Think about it.")} aria-label="Play a sample">
        <Volume2 size={15} />
      </button>
    </span>
  );
}
