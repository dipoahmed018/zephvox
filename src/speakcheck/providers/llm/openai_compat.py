"""Any OpenAI-compatible chat endpoint: Ollama (default), llama.cpp server, vLLM, LM Studio, cloud APIs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ...engine.errors import LLMError
from ...engine.capabilities import which
from ..base import Availability, Download, LLMProvider, ProviderSettings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json_reply(content: str) -> dict[str, Any]:
    text = _FENCE.sub("", _THINK.sub("", content).strip()).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM did not return valid JSON: {e}: {text[:200]!r}") from e
    if not isinstance(data, dict):
        raise LLMError(f"LLM returned JSON {type(data).__name__}, expected an object")
    return data


OLLAMA_APPROX_GB = {"qwen3:4b": 2.5, "qwen3:8b": 5.2, "qwen3:14b": 9.3, "qwen3:32b": 20.0}


class OpenAICompatLLM(LLMProvider):
    name = "openai-compat"

    class Settings(ProviderSettings):
        base_url: str = "http://localhost:11434/v1"
        model: str = "qwen3:8b"
        api_key_env: str | None = None  # name of the env var holding the key, for cloud endpoints
        temperature: float = 0.0
        timeout: float = 300.0
        max_retries: int = 2
        # Hard cap on reply length: with forced JSON some models never stop generating.
        max_tokens: int = 2048
        # Qwen3's soft switch; harmless for other models. Grammar checking doesn't need reasoning traces.
        no_think: bool = True
        # Require `model` in the server's model list (turn off for servers that name models differently).
        check_model: bool = True
        # Launch a local server on demand and stop it after the analysis (only if we started it).
        autostart: bool = True
        serve_command: list[str] = ["ollama", "serve"]
        start_timeout: float = 60.0

    def __init__(self, *args: Any, transport: httpx.BaseTransport | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._transport = transport
        self._proc: subprocess.Popen | None = None

    def _client(self, timeout: float) -> httpx.Client:
        headers = {}
        if self.settings.api_key_env:
            key = os.environ.get(self.settings.api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return httpx.Client(
            base_url=self.settings.base_url.rstrip("/"), headers=headers, timeout=timeout, transport=self._transport
        )

    def _list_models(self, timeout: float = 3.0) -> list[str]:
        """Raises httpx.HTTPError / ValueError when the server isn't answering."""
        with self._client(timeout=timeout) as client:
            resp = client.get("/models")
            resp.raise_for_status()
            return [m.get("id") for m in resp.json().get("data", [])]

    def _model_problem(self, models: list[str]) -> str | None:
        if self.settings.check_model and self.settings.model not in models:
            return f"model {self.settings.model!r} not available (for Ollama: ollama pull {self.settings.model})"
        return None

    def _is_local_ollama(self) -> bool:
        url = urlparse(self.settings.base_url)
        return url.hostname in ("localhost", "127.0.0.1", "::1") and (
            url.port == 11434 or os.path.basename(self.settings.serve_command[0] if self.settings.serve_command else "")
            == "ollama"
        )

    def downloads(self) -> list[Download]:
        if not self._is_local_ollama():
            return []
        return [Download("ollama", self.settings.model, OLLAMA_APPROX_GB.get(self.settings.model))]

    def _can_autostart(self) -> bool:
        host = urlparse(self.settings.base_url).hostname
        return (
            self.settings.autostart
            and host in ("localhost", "127.0.0.1", "::1")
            and bool(self.settings.serve_command)
            and self.services.caps.has_binary(self.settings.serve_command[0])
        )

    def check_available(self) -> Availability:
        if self.settings.api_key_env and not os.environ.get(self.settings.api_key_env):
            return Availability(False, f"environment variable {self.settings.api_key_env} is not set")
        try:
            models = self._list_models()
        except (httpx.HTTPError, ValueError) as e:
            if self._can_autostart():
                return Availability(True, f"not running; `{' '.join(self.settings.serve_command)}` starts on demand")
            return Availability(False, f"cannot reach {self.settings.base_url} ({type(e).__name__})")
        problem = self._model_problem(models)
        return Availability(problem is None, problem or "")

    def capabilities(self) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "endpoint": self.settings.base_url,
            "json_schema": True,
            "autostart": self._can_autostart(),
        }

    def prepare(self) -> None:
        try:
            self._list_models()
            return  # already running — someone else owns it
        except (httpx.HTTPError, ValueError):
            pass
        if not self._can_autostart():
            raise LLMError(f"cannot reach {self.settings.base_url}")

        env = dict(os.environ)
        if os.path.basename(self.settings.serve_command[0]) == "ollama":
            url = urlparse(self.settings.base_url)
            env["OLLAMA_HOST"] = f"{url.hostname}:{url.port or 11434}"
        log = tempfile.TemporaryFile()
        command = [which(self.settings.serve_command[0]) or self.settings.serve_command[0],
                   *self.settings.serve_command[1:]]  # fmt: skip
        self._proc = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True
        )
        deadline = time.monotonic() + self.settings.start_timeout
        while True:
            if self._proc.poll() is not None:
                log.seek(0)
                tail = log.read().decode(errors="replace").strip().splitlines()[-3:]
                self._proc = None
                raise LLMError(f"`{' '.join(self.settings.serve_command)}` exited: {' | '.join(tail)}")
            try:
                models = self._list_models(timeout=1.0)
                break
            except (httpx.HTTPError, ValueError):
                if time.monotonic() > deadline:
                    self.close()
                    raise LLMError(f"server did not answer within {self.settings.start_timeout:.0f}s") from None
                time.sleep(0.25)
        if problem := self._model_problem(models):
            self.close()
            raise LLMError(problem)

    def close(self) -> None:
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        if self.settings.no_think:
            user = f"{user}\n\n/no_think"
        body = {
            "model": self.settings.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        }
        last_error: Exception | None = None
        with self._client(timeout=self.settings.timeout) as client:
            for _attempt in range(self.settings.max_retries + 1):
                try:
                    resp = client.post("/chat/completions", json=body)
                    resp.raise_for_status()
                    choice = resp.json()["choices"][0]
                    content = choice["message"]["content"]
                except (httpx.TransportError, httpx.HTTPStatusError) as e:
                    last_error = e
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                        break  # client errors won't fix themselves
                    continue
                except (KeyError, IndexError, ValueError) as e:
                    raise LLMError(f"Unexpected response shape from {self.settings.base_url}: {e}") from e
                if choice.get("finish_reason") == "length":
                    raise LLMError(f"Reply was cut off at max_tokens={self.settings.max_tokens}")
                return parse_json_reply(content or "")
        raise LLMError(f"LLM request to {self.settings.base_url} failed: {last_error}")
