"""Run with: uv run pytest plugins/zephvox-espeak/tests (needs no espeak install)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestBundledEspeak:
    def fake_modules(self, monkeypatch):
        import sys
        from types import ModuleType, SimpleNamespace

        calls = {}
        loader = ModuleType("espeakng_loader")
        loader.get_library_path = lambda: "/wheel/libespeak-ng.so"
        loader.get_data_path = lambda: "/wheel/espeak-ng-data"
        wrapper = ModuleType("phonemizer.backend.espeak.wrapper")
        wrapper.EspeakWrapper = SimpleNamespace(set_library=lambda p: calls.update(lib=p),
                                                set_data_path=lambda p: calls.update(data=p))  # fmt: skip
        monkeypatch.setitem(sys.modules, "espeakng_loader", loader)
        monkeypatch.setitem(sys.modules, "phonemizer.backend.espeak.wrapper", wrapper)
        return calls

    def test_uses_wheel_library_by_default(self, monkeypatch):
        import zephvox_espeak as espeak

        calls = self.fake_modules(monkeypatch)
        monkeypatch.delenv("PHONEMIZER_ESPEAK_LIBRARY", raising=False)
        monkeypatch.setattr(espeak.importlib.util, "find_spec", lambda n: object())
        assert espeak.use_bundled_espeak() is True
        assert calls == {"lib": "/wheel/libespeak-ng.so", "data": "/wheel/espeak-ng-data"}

    def test_user_choice_or_missing_wheel_leaves_phonemizer_alone(self, monkeypatch):
        import zephvox_espeak as espeak

        calls = self.fake_modules(monkeypatch)
        monkeypatch.setenv("PHONEMIZER_ESPEAK_LIBRARY", "/mine/libespeak-ng.so")
        assert espeak.use_bundled_espeak() is False
        monkeypatch.delenv("PHONEMIZER_ESPEAK_LIBRARY")
        monkeypatch.setattr(espeak.importlib.util, "find_spec", lambda n: None)
        assert espeak.use_bundled_espeak() is False
        assert calls == {}
