import pytest

from speakcheck.engine.engine import Engine
from speakcheck.engine.errors import PluginNotFound, ProviderUnavailable, RecordingError
from pathlib import Path

from tests.conftest import FakeCapture, FakePhonemes, FakeSTT


def test_analyze_file_end_to_end(engine, wav_file):
    events = []
    engine.events.subscribe(events.append)
    result = engine.analyze(wav_file)

    assert result.sentences == ["I think we should go now.", "Yesterday he go to market."]
    assert result.sentence_spans == [(0.0, 1.6), (1.8, 3.0)]
    pron = result.by_analyzer("pronunciation")
    gram = result.by_analyzer("grammar")
    assert [(f.target, f.category) for f in pron] == [("think", "θ→s")]
    assert [(f.said, f.expected, f.segment_index) for f in gram] == [("he go", "he went", 1)]
    assert result.providers == {"stt": "fake-stt", "g2p": "fake-g2p", "phonemes": "fake-phonemes", "llm": "fake-llm"}
    assert result.duration == 3.0
    assert set(result.timings) == {"transcript", "expected_phonemes", "heard_phonemes"}

    types = [e.type for e in events]
    assert "provider_fallback" in types  # broken-stt was skipped
    assert types.count("finding") == 2
    # Persisted and reloadable.
    session = engine.sessions.get(result.session_id)
    assert session.audio_path.exists()
    assert engine.sessions.load_result(session) == result


def test_grammar_only_never_touches_phoneme_provider(engine, wav_file):
    result = engine.analyze(wav_file, analyzers=["grammar"])
    assert FakePhonemes.calls == 0
    assert "phonemes" not in result.providers and result.analyzers == ["grammar"]
    assert FakeSTT.calls == 1


def test_provider_is_resolved_once_and_cached(engine):
    assert engine.provider("stt") is engine.provider("stt")


def test_no_usable_provider(engine):
    engine.config.providers["stt"] = ["broken-stt", "missing"]
    with pytest.raises(ProviderUnavailable) as e:
        engine.provider("stt")
    assert "broken-stt: not installed" in str(e.value) and "missing" in str(e.value)


def test_unknown_analyzer(engine, wav_file):
    with pytest.raises(PluginNotFound):
        engine.analyze(wav_file, analyzers=["fluency"])


def test_recording_lifecycle(engine):
    assert not engine.is_recording() and engine.recording_status() is None
    recording = engine.start_recording()
    assert engine.is_recording() and recording.mode == "analysis" and recording.session_id
    status = engine.recording_status()
    assert status["mode"] == "analysis" and status["elapsed"] >= 0 and status["level"] == 0.25
    with pytest.raises(RecordingError, match="Already recording"):
        engine.start_recording()

    # A fresh engine (e.g. a second CLI process) can stop it from the saved state.
    other = Engine(config=engine.config, registry=engine.registry, caps=engine.caps)
    stopped = other.stop_recording()
    assert stopped == recording and not other.is_recording()
    session = other.sessions.get(recording.session_id)
    assert FakeCapture.stopped == [{"path": str(session.audio_path)}]
    result = other.analyze(stopped)
    assert result.session_id == recording.session_id
    with pytest.raises(RecordingError, match="Not recording"):
        other.stop_recording()
    with pytest.raises(RecordingError, match="Unknown recording mode"):
        other.start_recording(mode="karaoke")


def test_cancel_recording_discards_audio(engine):
    rec = engine.start_recording()
    engine.cancel_recording()
    assert not engine.is_recording()
    assert [s.id for s in engine.sessions.list()] == []
    practice = engine.start_recording(mode="practice", meta={"target": "think"})
    assert practice.session_id is None and practice.meta == {"target": "think"}
    engine.cancel_recording()
    assert not Path(practice.path).exists()
    assert rec.mode == "analysis"


def test_reference_text_skips_stt_and_save_false_leaves_no_session(engine, wav_file):
    result = engine.analyze(wav_file, analyzers=["pronunciation"], reference_text="I think we should go now.",
                            save=False)  # fmt: skip
    assert FakeSTT.calls == 0
    assert result.session_id == "" and engine.sessions.list() == []
    assert result.sentences == ["I think we should go now."]
    assert "stt" not in result.providers


def test_practice_scores_and_logs_attempts(engine, wav_file):
    events = []
    engine.events.subscribe(events.append, types=["practice_result"])
    attempt = engine.practice("think", wav_file, source_session="s1")
    # Fake recognizer "hears" sentence 1 (I sink we should go now) for a one-word target.
    assert attempt.target == "think" and 0 <= attempt.score < 85 and not attempt.passed
    assert attempt.words[0]["phones"][0]["status"] in ("wrong", "extra", "missing", "ok")
    assert events and events[0].data["attempt"]["target"] == "think"
    stats = engine.practice_store.stats("think")
    assert stats["attempts"] == 1 and stats["best"] == attempt.score and not stats["passed"]


def test_practice_practice_recording_object(engine):
    rec = engine.start_recording(mode="practice", meta={"target": "go"})
    rec = engine.stop_recording()
    attempt = engine.practice("go", rec)
    assert attempt.audio == rec.path


def test_release_closes_one_provider(engine):
    llm = engine.provider("llm")
    closed = []
    llm.close = lambda: closed.append(True)
    engine.release("llm")
    engine.release("llm")  # already gone: no-op
    assert closed == [True] and "llm" not in engine._providers


def test_feedback_dismissal_hides_from_history_and_weak_words(engine, wav_file):
    result = engine.analyze(wav_file)
    session = engine.sessions.get(result.session_id)
    pron_index = next(i for i, f in enumerate(result.findings) if f.analyzer == "pronunciation")
    assert engine.weak_words() == [{"target": "think", "mistakes": 1, "best": None, "attempts": 0}]
    engine.sessions.set_feedback(session, pron_index, "dismissed")
    h = engine.history()
    assert h["dismissed"] == 1 and "pronunciation" not in h["targets"]
    assert engine.weak_words() == []
    assert engine.sessions.set_feedback(session, pron_index, None) == {}


def test_list_providers_marks_selection(engine):
    statuses = {(s.kind, s.name): s for s in engine.list_providers()}
    assert statuses[("stt", "fake-stt")].selected
    broken = statuses[("stt", "broken-stt")]
    assert not broken.available and broken.reason == "not installed" and broken.preference == 0
    assert not statuses[("stt", "broken-stt")].selected


def test_doctor_and_history(engine, wav_file):
    engine.analyze(wav_file)
    engine.analyze(wav_file, analyzers=["pronunciation"])
    doctor = engine.doctor()
    assert doctor["analyzers"] == ["grammar", "practice", "pronunciation"]
    assert doctor["broken_plugins"] == {}
    assert doctor["system"]["binaries"]["ffmpeg"] is True

    engine.sessions.create()  # a session without a result is ignored
    h = engine.history()
    assert h["sessions"] == 2
    assert h["targets"]["pronunciation"] == [("think", 2)]
    assert h["categories"]["grammar"] == [("verb-tense", 1)]


def test_close_releases_providers(engine):
    engine.provider("stt")
    engine.close()
    assert engine._providers == {}


def test_default_construction_detects_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAKCHECK_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("SPEAKCHECK_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("speakcheck.engine.engine.detect", lambda: "caps!")
    e = Engine()
    assert e.caps == "caps!"
    assert e.sessions.root == tmp_path / "home" / "sessions"


def test_prepare_failure_falls_back_and_closes(engine, registry):
    from speakcheck.engine.errors import LLMError
    from tests.conftest import FakeLLM

    closed = []

    class FailingLLM(FakeLLM):
        name = "failing-llm"

        def prepare(self):
            raise LLMError("server crashed")

        def close(self):
            closed.append(True)

    registry.register("llm", "failing-llm", FailingLLM)
    engine.config.providers["llm"] = ["failing-llm", "fake-llm"]
    events = []
    engine.events.subscribe(events.append, types=["provider_fallback"])
    assert engine.provider("llm").name == "fake-llm"
    assert closed == [True]
    assert "failing-llm: server crashed" in events[0].data["skipped"][0]
