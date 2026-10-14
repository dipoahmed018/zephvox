import { initialState, reduce, type EngineState } from "../engine";
import { explainError } from "../lib/errors";
import { alignSounds, splitSounds } from "../lib/align";
import { gatesFor } from "../lib/stages";

describe("alignSounds", () => {
  it("lines up a missing sound as a gap", () => {
    expect(alignSounds(splitSounds("/t ə m ɑ ɹ oʊ/"), splitSounds("/t ə m ɑ ɹ/"))).toEqual([
      ["t", "t"],
      ["ə", "ə"],
      ["m", "m"],
      ["ɑ", "ɑ"],
      ["ɹ", "ɹ"],
      ["oʊ", null],
    ]);
  });

  it("pairs substitutions and shows extra sounds", () => {
    expect(alignSounds(["θ", "ɪ", "ŋ", "k"], ["s", "ɪ", "ŋ", "k"])[0]).toEqual(["θ", "s"]);
    expect(alignSounds(["k", "æ", "t"], ["k", "æ", "t", "ə"])).toEqual([
      ["k", "k"],
      ["æ", "æ"],
      ["t", "t"],
      [null, "ə"],
    ]);
    expect(alignSounds([], [])).toEqual([]);
  });
});

describe("gatesFor", () => {
  it("shows only the checks that will run, each with its state", () => {
    expect(gatesFor([], ["pronunciation"]).map((g) => g.label)).toEqual(["Transcribe", "Sounds"]);
    const gates = gatesFor(
      [
        { key: "transcript", state: "done" },
        { key: "expected_phonemes", state: "running" },
      ],
      ["pronunciation", "grammar"],
    );
    expect(gates).toEqual([
      { label: "Transcribe", state: "done" },
      { label: "Sounds", state: "running" },
      { label: "Grammar", state: "waiting" },
    ]);
  });

  it("finishes the last gate and counts an upload as transcribing", () => {
    const gates = gatesFor(
      [
        { key: "upload", state: "done" },
        { key: "transcript", state: "done" },
        { key: "analyzer:grammar", state: "done" },
      ],
      ["grammar"],
    );
    expect(gates).toEqual([
      { label: "Transcribe", state: "done" },
      { label: "Grammar", state: "done" },
    ]);
  });
});

describe("analysis failures", () => {
  it("explains a missing grammar model in plain words, with the fix", () => {
    const e = explainError(
      "No usable llm provider: openai-compat: model 'qwen3:14b' not available (for Ollama: ollama pull qwen3:14b)",
    );
    expect(e.title).toBe("The grammar model (qwen3:14b) isn't downloaded");
    expect(e.command).toBe("ollama pull qwen3:14b");
    expect(explainError("No usable stt provider: hf-whisper: not installed").title).toBe("Nothing available for speech recognition");
    expect(explainError("boom").detail).toBe("boom");
  });

  it("remembers the failure until the next analysis starts", () => {
    const send = (s: EngineState, event: string, data: Record<string, unknown> = {}) => reduce(s, { type: "server", event, data });
    let s = send(initialState, "job_started", { job: "analysis" });
    s = send(s, "job_error", { job: "analysis", message: "model 'x' not available" });
    expect(s.analysisError).toBe("model 'x' not available");
    expect(s.notices).toEqual([]); // shown as a card, not a notice
    expect(send(s, "job_error", { job: "practice", message: "other" }).notices).toHaveLength(1);
    expect(send(s, "recording_started", { mode: "practice" }).analysisError).not.toBeNull();
    expect(send(s, "recording_started", { mode: "analysis" }).analysisError).toBeNull();
  });
});
