"""Opt-in tests with real models. Run with e.g.:

    uv run python scripts/make_fixtures.py
    uv run pytest -m "audio and models"          # Whisper + CMUdict/espeak + wav2vec2
    uv run pytest -m gpu                          # same, asserting the GPU is used
    uv run pytest -m llm                          # live Ollama qwen3:8b
"""

from __future__ import annotations

from pathlib import Path

import pytest

from speakcheck.engine.capabilities import detect_gpu
from speakcheck.engine.config import Config, EngineSettings
from speakcheck.engine.engine import Engine
from speakcheck.engine.models import Segment, Transcript, Word

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name: str) -> Path:
    path = FIXTURES / f"{name}.wav"
    if not path.exists():
        pytest.skip(f"{path.name} missing — run scripts/make_fixtures.py")
    return path


@pytest.fixture(scope="module")
def engine(tmp_path_factory) -> Engine:
    config = Config(engine=EngineSettings(data_dir=tmp_path_factory.mktemp("data")))
    e = Engine(config=config)
    yield e
    e.close()


@pytest.mark.audio
@pytest.mark.models
def test_clean_speech_has_few_pronunciation_findings(engine):
    result = engine.analyze(fixture("clean"), analyzers=["pronunciation"])
    assert "market" in " ".join(result.sentences).lower()
    # TTS is not a perfect speaker, but correct speech must not light up everywhere.
    assert len(result.findings) <= 2, [f.target for f in result.findings]


@pytest.mark.audio
@pytest.mark.models
def test_deliberate_mispronunciations_are_found(engine):
    result = engine.analyze(fixture("mispronounced"), analyzers=["pronunciation"])
    targets = {f.target.lower(): f for f in result.findings}
    text = " ".join(result.sentences).lower()
    # Whisper must have recovered the intended words for the check to be meaningful.
    if "think" in text:
        assert "think" in targets and "θ" in targets["think"].expected
    if "very" in text:
        assert "very" in targets


@pytest.mark.gpu
def test_gpu_is_visible_to_torch():
    gpu = detect_gpu()
    assert gpu is not None, "torch sees no GPU (ROCm: check rocminfo, render/video groups, HSA_OVERRIDE_GFX_VERSION)"


@pytest.mark.llm
def test_live_llm_finds_grammar_mistake(tmp_path):
    from speakcheck.analyzers.base import AnalysisContext
    from speakcheck.analyzers.grammar.analyzer import GrammarAnalyzer

    engine = Engine(config=Config(engine=EngineSettings(data_dir=tmp_path)))
    words = [Word(t, i * 0.3, i * 0.3 + 0.3) for i, t in enumerate("Yesterday he go to the market.".split())]
    transcript = Transcript([Segment("Yesterday he go to the market.", 0, 2, words)], verbatim="partial")
    warnings: list[str] = []
    ctx = AnalysisContext({"transcript": transcript}.__getitem__, engine.provider, warnings.append)
    try:
        findings = GrammarAnalyzer().analyze(ctx)
    finally:
        engine.close()  # stops the Ollama server if autostart launched it
    assert any("go" in f.said and "went" in f.expected for f in findings), (findings, warnings)
