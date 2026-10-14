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
