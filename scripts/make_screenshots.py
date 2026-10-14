"""Regenerate the README / website screenshots in docs/assets/screenshots/.

They show made-up sample sentences, never your own recordings: the page is opened against a running
zephvox, and the data it would read is replaced in the browser (nothing is changed in the app).

    uv run zephvox serve                                             # in another terminal
    uvx --with playwright python scripts/make_screenshots.py         # needs Chromium: `playwright install chromium`

Options: --url http://127.0.0.1:8765  --out docs/assets/screenshots
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from playwright.sync_api import Page, Route, sync_playwright

SENTENCES = [
    "Yesterday I went to the library and did a thorough search for books.",
    "She don't like coffee, but I think it tastes great.",
    "The weather in the north is rather warm this month.",
]


def finding(analyzer, sentence_index, target, said, expected, span, category, explanation, time_span=None):
    return {
        "analyzer": analyzer, "sentence": SENTENCES[sentence_index], "target": target, "said": said,
        "expected": expected, "explanation": explanation, "category": category,
        "segment_index": sentence_index, "word_span": span, "time_span": time_span, "confidence": 0.93,
        "details": {},
    }  # fmt: skip


REPORT = {
    "session_id": "demo-1",
    "audio_path": "",
    "sentences": SENTENCES,
    "sentence_spans": [[0.0, 4.6], [5.0, 8.9], [9.4, 13.5]],
    "findings": [
        finding("pronunciation", 0, "thorough", "/t ʌ ɹ oʊ/", "/θ ʌ ɹ oʊ/", [9, 9], "θ→t",
                "You said 't' as in top instead of 'th' as in think.", [3.1, 3.6]),
        finding("grammar", 1, "She don't", "She don't", "She doesn't", [0, 1], "subject-verb agreement",
                "Use \"doesn't\" with he, she and it."),
        finding("pronunciation", 1, "think", "/s ɪ ŋ k/", "/θ ɪ ŋ k/", [6, 6], "θ→s",
                "You said 's' as in see instead of 'th' as in think.", [7.4, 7.8]),
        finding("pronunciation", 2, "rather", "/ɹ ɑ d ɚ/", "/ɹ æ ð ɚ/", [6, 6], "ð→d",
                "You said 'd' as in dog instead of 'th' as in this.", [11.2, 11.6]),
        finding("pronunciation", 2, "month", "/m ʌ n s/", "/m ʌ n θ/", [9, 9], "θ→s",
                "The last sound was 's' instead of 'th' as in think.", [12.7, 13.2]),
    ],
    "providers": {}, "analyzers": ["pronunciation", "grammar"], "warnings": [], "timings": {},
    "duration": 13.5, "created": "2026-10-15T09:41:00",
}  # fmt: skip

SESSIONS = [
    {"id": "demo-1", "created": "2026-10-15T09:41:00", "duration": 13.5, "counts": {"pronunciation": 4, "grammar": 1},
     "preview": SENTENCES[0]},
    {"id": "demo-2", "created": "2026-10-14T18:20:00", "duration": 62.0, "counts": {"pronunciation": 6, "grammar": 2},
     "preview": "I would like to practice speaking about my work and my weekend plans."},
    {"id": "demo-3", "created": "2026-10-13T08:05:00", "duration": 31.0, "counts": {"pronunciation": 3},
     "preview": "The three of us walked through the park before the rain started."},
]  # fmt: skip

WEAK = [
    {"target": "thorough", "mistakes": 4, "best": 62, "attempts": 5},
    {"target": "rather", "mistakes": 3, "best": 71, "attempts": 4},
    {"target": "month", "mistakes": 2, "best": None, "attempts": 0},
    {"target": "think", "mistakes": 2, "best": 80, "attempts": 3},
    {"target": "clothes", "mistakes": 1, "best": None, "attempts": 0},
]  # fmt: skip

STATS = {
    "target": "thorough", "attempts": 6, "best": 62, "last": 54, "passed": False,
    "history": [{"score": s, "passed": s >= 85, "at": ""} for s in (31, 38, 45, 58, 62, 54)],
}  # fmt: skip

ATTEMPT = {
    "target": "thorough", "score": 54, "passed": False, "status": "ok", "at": "", "audio": None,
    "source_session": None,
    "words": [{
        "word": "thorough", "score": 54, "passed": False, "status": "ok",
        "explanation": "You said 't' as in top instead of 'th' as in think.",
        "tip": "Put the tip of your tongue lightly between your teeth and let the air flow out, with no stop.",
        "accepted": ["θ ʌ ɹ oʊ"],
        "phones": [
            {"expected": "θ", "heard": "t", "status": "wrong"},
            {"expected": "ʌ", "heard": "ʌ", "status": "ok"},
            {"expected": "ɹ", "heard": "ɹ", "status": "ok"},
            {"expected": "oʊ", "heard": "oʊ", "status": "ok"},
        ],
    }],
}  # fmt: skip

FAKE_EVENTS = """
window.EventSource = class { constructor() { window.__es = this; setTimeout(() => this.onopen && this.onopen(), 50); } close() {} };
window.__send = (type, data) => window.__es.onmessage({ data: JSON.stringify({ type, data: data || {} }) });
"""


def install_routes(page: Page) -> None:
    """Replace what the page reads with sample data; refuse anything that would change the app."""

    def respond(route: Route, body) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def patched(route: Route, change) -> None:
        resp = route.fetch()
        data = resp.json()
        change(data)
        respond(route, data)

    def handle(route: Route) -> None:
        request = route.request
        path = request.url.split("/api", 1)[1].split("?")[0]
        if request.method != "GET":
            return respond(route, {})
        if path == "/sessions":
            return respond(route, SESSIONS)
        if path.startswith("/sessions/"):
            return respond(route, {"result": REPORT, "feedback": {}})
        if path == "/practice/weak":
            return respond(route, WEAK)
        if path == "/practice/stats":
            return respond(route, STATS)
        if path == "/history":
            return respond(route, {"sessions": 3, "dismissed": 0, "categories": {
                "pronunciation": [["θ→t", 5], ["θ→s", 4], ["ð→d", 3], ["v→w", 1]],
                "grammar": [["subject-verb agreement", 2], ["verb-tense", 1]]}, "targets": {}})  # fmt: skip
        if path == "/devices":
            return respond(route, {"provider": "pipewire", "selected": None, "devices": [
                {"id": "mic-1", "name": "Built-in microphone", "is_default": True},
                {"id": "mic-2", "name": "USB headset", "is_default": False}]})  # fmt: skip
        if path == "/config":
            def clean(d):
                d["missing_models"], d["downloads"], d["overlay"], d["in_file"] = [], {}, {}, []
            return patched(route, clean)
        if path == "/profiles":
            def clean_profiles(d):
                d["needs"], d["models"] = [], []
            return patched(route, clean_profiles)
        return route.continue_()

    page.route("**/api/**", handle)


def shoot_theme(browser, base: str, out: Path, theme: str) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme=theme)

    def screen(name: str, route: str, after=None) -> None:
        """A fresh page per screen, so one screen's state never leaks into the next."""
        page = context.new_page()
        page.add_init_script(FAKE_EVENTS + f"localStorage.setItem('zephvox.theme', '{theme}');")
        install_routes(page)
        page.goto(f"{base}/#{route}")
        page.wait_for_timeout(900)
        if after:
            after(page)
        page.wait_for_timeout(1300)
        page.screenshot(path=str(out / f"{name}-{theme}.png"))
        page.close()

    def practiced(page: Page) -> None:
        page.evaluate("__send('practice_target', {target: {text: 'thorough', session_id: null}})")
        page.evaluate(f"__send('practice_result', {{attempt: {json.dumps(ATTEMPT)}}})")

    def recording(page: Page) -> None:
        page.evaluate("__send('recording_started', {mode: 'analysis'})")
        page.evaluate(
            "setInterval(() => { const t = performance.now() / 1000;"
            "__send('level', {level: Math.min(1, 0.25 + Math.abs(Math.sin(t * 5.1)) * 0.6 * Math.abs(Math.sin(t * 0.7 + 1))),"
            " elapsed: 4 + (t % 5)}) }, 60)"
        )

    screen("report", "/report/demo-1")
    screen("practice", "/practice?w=thorough&ipa=%2F%CE%B8%20%CA%8C%20%C9%B9%20o%CA%8A%2F", practiced)
    screen("home", "/home", recording)
    screen("settings", "/status")
    context.close()


def shoot(base: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        chromium = p.chromium.launch(executable_path=shutil.which("chromium") or shutil.which("chromium-browser"))
        for theme in ("light", "dark"):
            shoot_theme(chromium, base, out, theme)
        chromium.close()


OG_HTML = """<!doctype html><meta charset="utf-8"><style>
@font-face{font-family:F;src:url(fonts/fraunces-latin-opsz-normal.woff2);font-weight:100 900}
@font-face{font-family:F;font-style:italic;src:url(fonts/fraunces-latin-opsz-italic.woff2);font-weight:100 900}
@font-face{font-family:N;src:url(fonts/nunito-sans-latin-wght-normal.woff2);font-weight:200 1000}
body{margin:0;width:1200px;height:630px;position:relative;overflow:hidden;color:#1c2b3a;font-family:N,sans-serif;
background:linear-gradient(180deg,#dcebf8,#f4f8fc)}
svg.w{position:absolute;inset:0}
.mark{position:absolute;left:84px;top:78px;display:flex;align-items:center;gap:18px;font:italic 300 46px F}
.mark img{width:68px;height:68px;border-radius:19px}
h1{position:absolute;left:84px;top:210px;margin:0;font:300 112px/1.02 F;letter-spacing:-.02em}
h1 em{font-style:italic}
p{position:absolute;left:88px;top:470px;margin:0;font:600 32px/1.4 N;color:#5a6b7d;width:900px}
</style>
<svg class="w" viewBox="0 0 1200 630" fill="none" stroke="#3a78ae" stroke-linecap="round" stroke-width="2.4">
%LINES%</svg>
<div class="mark"><img src="logo.svg" alt="">zephvox</div>
<h1>Say it.<br><em>See what to fix.</em></h1>
<p>Record English anywhere, then see the sounds and sentences to work on.</p>"""


def og_image(assets: Path) -> None:
    """The 1200x630 preview shown when the website is shared."""
    import math

    lines = []
    for i in range(11):
        y = 60 + i * 52
        d = " ".join(f"{'M' if x == 0 else 'L'}{x},{y + 14 * math.sin(x / 95 + i * 0.7):.1f}" for x in range(0, 1241, 20))
        lines.append(f'<path d="{d}" stroke-opacity="{0.10 + 0.05 * (i % 3):.2f}" stroke-dasharray="{180 + i * 12} {70 + i * 9}"/>')
    page_file = assets / "_og.html"
    page_file.write_text(OG_HTML.replace("%LINES%", "\n".join(lines)))
    try:
        with sync_playwright() as p:
            chromium = p.chromium.launch(executable_path=shutil.which("chromium") or shutil.which("chromium-browser"))
            page = chromium.new_page(viewport={"width": 1200, "height": 630})
            page.goto(page_file.resolve().as_uri())
            page.wait_for_timeout(600)
            page.screenshot(path=str(assets / "og.png"))
            chromium.close()
    finally:
        page_file.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("docs/assets/screenshots"))
    args = parser.parse_args()
    shoot(args.url.rstrip("/"), args.out)
    og_image(args.out.parent)
    print(f"Wrote {len(list(args.out.glob('*.png')))} screenshots to {args.out}, and {args.out.parent / 'og.png'}")
