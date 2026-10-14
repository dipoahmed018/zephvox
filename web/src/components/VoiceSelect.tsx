import { Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, speak } from "@/api";
import { useAction } from "@/engine";

interface Voice {
  id: string;
  label: string;
}

const SAMPLE = "Think about it.";

/** Choose the reference voice used for "Hear it" (saved in the engine's settings). */
export function VoiceSelect({ id, onSaved }: { id?: string; onSaved?: () => void }) {
  const run = useAction();
  const [provider, setProvider] = useState("");
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    run(api.voices).then((v) => {
      if (!v) return;
      setProvider(v.provider);
      setVoices(v.voices);
      setSelected(v.selected ?? v.voices[0]?.id ?? "");
    });
  }, []);

  const change = async (voice: string) => {
    setSelected(voice);
    if (await run(() => api.saveSettings({ tts: { provider, voice } }))) {
      onSaved?.();
      speak(SAMPLE);
    }
  };

  const preview = (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="outline" size="icon" aria-label="Play a sample" onClick={() => speak(SAMPLE)}>
          <Volume2 />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Play a sample</TooltipContent>
    </Tooltip>
  );

  if (voices !== null && voices.length === 0) {
    return (
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        {provider ? `${provider} (one voice)` : "Your browser's voice"}
        {preview}
      </span>
    );
  }
  return (
    <>
      <Select value={selected} onValueChange={change} disabled={voices === null}>
        <SelectTrigger id={id} aria-label="Reference voice" className="h-10 w-full min-w-0 bg-card sm:w-60">
          <SelectValue placeholder="Loading…" />
        </SelectTrigger>
        <SelectContent position="popper" className="max-h-80 rounded-xl">
          {voices?.map((v) => (
            <SelectItem key={v.id} value={v.id}>
              {v.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {preview}
    </>
  );
}
