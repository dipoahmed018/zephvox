// Engine errors are written for logs; these say what happened and what to do, in plain words.

export interface Explained {
  title: string;
  detail: string;
  /** A terminal command that fixes it, when there is one. */
  command?: string;
  /** Changing the profile in Settings is another way out. */
  settings?: boolean;
}

export function explainError(message: string): Explained {
  const model = message.match(/model '([^']+)' not available/);
  if (model) {
    return {
      title: `The grammar model (${model[1]}) isn't downloaded`,
      detail: "Download it, or pick a profile whose model you already have.",
      command: `ollama pull ${model[1]}`,
      settings: true,
    };
  }
  const provider = message.match(/^No usable (\w+) provider: (.*)$/);
  if (provider) {
    const what: Record<string, string> = {
      stt: "speech recognition",
      llm: "grammar checking",
      phonemes: "sound recognition",
      g2p: "the pronunciation dictionary",
      capture: "the microphone",
      tts: "the reference voice",
    };
    return { title: `Nothing available for ${what[provider[1]] ?? provider[1]}`, detail: provider[2], settings: true };
  }
  return { title: "The analysis stopped with an error", detail: message };
}
