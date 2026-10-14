"""Planner, artifacts, registry, config, capabilities, sessions."""

from datetime import datetime
from importlib.metadata import EntryPoint
from types import SimpleNamespace

import pytest

from speakcheck.engine import capabilities
from speakcheck.engine.artifacts import ArtifactRegistry, ArtifactSpec, ArtifactStore
from speakcheck.engine.capabilities import SystemCapabilities, detect, detect_ram_gb
from speakcheck.engine.config import Config, load_config
from speakcheck.engine.errors import ConfigError, PlanError, PluginNotFound, SpeakcheckError
from speakcheck.engine.models import AnalysisResult, Finding
from speakcheck.engine.planner import plan
from speakcheck.engine.registry import Registry
from speakcheck.engine.session import SessionStore


class TestPlanner:
    def test_grammar_only_skips_phoneme_work(self):
        p = plan([(("transcript",), ("llm",))], ArtifactRegistry.default(), provided=("audio", "samples"))
        assert p.artifacts == ["transcript"]
        assert p.provider_kinds == ["stt", "llm"]

    def test_pronunciation_needs_everything_in_dependency_order(self):
        needs = ("transcript", "expected_phonemes", "heard_phonemes")
        p = plan([(needs, ())], ArtifactRegistry.default())
        assert p.artifacts == ["samples", "transcript", "expected_phonemes", "heard_phonemes"]
        assert p.provider_kinds == ["stt", "g2p", "phonemes"]

    def test_unknown_artifact(self):
        with pytest.raises(PlanError, match="No producer for artifact 'nope'"):
            plan([(("nope",), ())], ArtifactRegistry.default())

    def test_cycle(self):
        reg = ArtifactRegistry()
        reg.register(ArtifactSpec("a", lambda s: 1, needs=("b",)))
        reg.register(ArtifactSpec("b", lambda s: 2, needs=("a",)))
        with pytest.raises(PlanError, match="cycle"):
            plan([(("a",), ())], reg)


class TestArtifactStore:
    def test_lazy_cached_with_timings_and_events(self):
        calls = []
        reg = ArtifactRegistry()
        reg.register(ArtifactSpec("x", lambda s: calls.append("x") or 1))
        reg.register(ArtifactSpec("y", lambda s: s.get("x") + 1, needs=("x",)))
        events = []
        store = ArtifactStore(reg, provider=lambda k: None)
        store.events.subscribe(lambda e: events.append((e.type, e.data["stage"])))
        assert store.get("y") == 2 and store.get("y") == 2
        assert calls == ["x"]
        assert set(store.timings) == {"x", "y"}
        assert events[0] == ("stage_started", "x")
        assert store.peek("missing", 7) == 7
        assert reg.keys() == ["x", "y"]

    def test_missing_producer(self):
        with pytest.raises(PlanError):
            ArtifactStore(ArtifactRegistry(), provider=lambda k: None).get("ghost")


class Plugin:
    pass


class TestRegistry:
    def _ep(self, name, value, group):
        return EntryPoint(name=name, value=value, group=group)

    def test_discovers_entry_points_and_records_broken(self):
        eps = {
            "speakcheck.stt": [self._ep("good", "tests.unit.test_core:Plugin", "speakcheck.stt"),
                               self._ep("bad", "no.such.module:X", "speakcheck.stt")],
        }  # fmt: skip
        reg = Registry(lambda group: eps.get(group, []))
        assert reg.get("stt", "good") is Plugin
        assert reg.names("stt") == ["good"]
        assert ("stt", "bad") in reg.broken

    def test_explicit_registration_wins(self):
        eps = {"speakcheck.stt": [self._ep("x", "tests.unit.test_core:Plugin", "speakcheck.stt")]}
        reg = Registry(lambda group: eps.get(group, []))
        reg.register("stt", "x", int)
        assert reg.get("stt", "x") is int

    def test_errors(self):
        reg = Registry(None)
        with pytest.raises(PluginNotFound, match="No stt plugin named 'x'"):
            reg.get("stt", "x")
        with pytest.raises(ValueError):
            reg.register("nonsense", "x", int)

    def test_builtin_entry_points_are_installed(self):
        reg = Registry()
        assert {"hf-whisper", "faster-whisper"} <= set(reg.names("stt"))
        assert {"pronunciation", "grammar"} <= set(reg.names("analyzers"))
        assert {"terminal", "markdown", "json"} <= set(reg.names("reporters"))
        assert reg.broken == {}


class TestConfig:
    def test_defaults_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAKCHECK_CONFIG", str(tmp_path / "none.toml"))
        monkeypatch.setenv("SPEAKCHECK_HOME", str(tmp_path / "home"))
        c = load_config()
        assert c.providers["stt"] == ["hf-whisper", "faster-whisper"]
        assert c.engine.data_dir == tmp_path / "home"

    def test_file_merges_per_kind(self, tmp_path):
        path = tmp_path / "c.toml"
        path.write_text(
            '[engine]\nanalyzers = ["grammar"]\ndata_dir = "~/sc"\n'
            '[providers]\nstt = ["faster-whisper"]\n'
            '[provider.faster-whisper]\nmodel = "base.en"\n'
            "[analyzer.grammar]\nbatch_size = 3\n"
        )
        c = load_config(path)
        assert c.engine.analyzers == ["grammar"]
        assert c.providers["stt"] == ["faster-whisper"] and c.providers["g2p"] == ["chain"]
        assert c.provider_settings("faster-whisper") == {"model": "base.en"}
        assert c.analyzer_settings("grammar") == {"batch_size": 3}
        assert c.provider_settings("other") == {} and "~" not in str(c.engine.data_dir)

    def test_errors(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "missing.toml")
        bad = tmp_path / "bad.toml"
        bad.write_text("[engine\n")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            load_config(bad)
        bad.write_text("[engine]\nunknown = 1\n")
        with pytest.raises(ConfigError, match="Invalid config"):
            load_config(bad)

    def test_overrides(self):
        c = Config().with_overrides(["stt=faster-whisper", "g2p = cmudict, espeak"])
        assert c.providers["stt"] == ["faster-whisper"]
        assert c.providers["g2p"] == ["cmudict", "espeak"]
        assert Config().providers["stt"] != ["faster-whisper"]  # original untouched
        with pytest.raises(ConfigError):
            Config().with_overrides(["stt"])
        with pytest.raises(ConfigError):
            Config().with_overrides(["stt="])


class TestCapabilities:
    def test_ram(self, tmp_path):
        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:       16777216 kB\nMemFree: 1 kB\n")
        assert detect_ram_gb(meminfo) == 16.0
        assert detect_ram_gb(tmp_path / "missing") == 0.0

    def test_detect_without_gpu_probe(self, monkeypatch):
        monkeypatch.setenv("FOO_API_KEY", "x")
        caps = detect(probe_gpu=False)
        assert caps.gpu is None
        assert "FOO_API_KEY" in caps.env_keys
        assert set(capabilities.KNOWN_BINARIES) <= set(caps.binaries)
        assert caps.to_dict()["gpu"] is None

    def test_has_binary_caches(self, monkeypatch):
        caps = SystemCapabilities()
        monkeypatch.setattr(capabilities.shutil, "which", lambda n: "/bin/" + n)
        assert caps.has_binary("x") is True
        monkeypatch.setattr(capabilities.shutil, "which", lambda n: None)
        assert caps.has_binary("x") is True  # cached
        assert SystemCapabilities.has_module("json") and not SystemCapabilities.has_module("no_such_mod")

    def test_gpu_detection_paths(self, monkeypatch):
        props = SimpleNamespace(total_memory=16e9)
        fake_cuda = SimpleNamespace(is_available=lambda: True, get_device_properties=lambda i: props,
                                    get_device_name=lambda i: "AMD Radeon RX 6800 XT")  # fmt: skip
        fake_torch = SimpleNamespace(cuda=fake_cuda, version=SimpleNamespace(hip="7.2"))
        monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
        monkeypatch.setattr(capabilities.importlib.util, "find_spec", lambda n: object())
        gpu = capabilities.detect_gpu()
        assert (gpu.backend, gpu.name, gpu.vram_gb) == ("rocm", "AMD Radeon RX 6800 XT", 16.0)

        fake_torch.version = SimpleNamespace(hip=None)
        assert capabilities.detect_gpu().backend == "cuda"
        fake_cuda.is_available = lambda: False
        assert capabilities.detect_gpu() is None
        fake_cuda.is_available = lambda: 1 / 0
        assert capabilities.detect_gpu() is None
        monkeypatch.setattr(capabilities.importlib.util, "find_spec", lambda n: None)
        assert capabilities.detect_gpu() is None


class TestSessions:
    def test_create_unique_list_and_roundtrip(self, tmp_path):
        store = SessionStore(tmp_path / "s")
        assert store.list() == []
        now = datetime(2026, 10, 13, 22, 0, 0)
        a, b = store.create(now), store.create(now)
        assert (a.id, b.id) == ("20261013-220000", "20261013-220000-2")
        assert [s.id for s in store.list()] == [a.id, b.id]
        assert store.load_result(a) is None

        finding = Finding("grammar", "He go.", "go", "go", "went", "Past.", "verb-tense",
                          word_span=(1, 1), time_span=(0.1, 0.2))  # fmt: skip
        result = AnalysisResult(a.id, str(a.audio_path), ["He go."], [finding], analyzers=["grammar"])
        store.save_result(a, result)
        loaded = store.load_result(store.get(a.id))
        assert loaded == result and loaded.by_analyzer("grammar") == [finding]

    def test_unknown_session(self, tmp_path):
        with pytest.raises(SpeakcheckError, match="No session"):
            SessionStore(tmp_path).get("nope")
