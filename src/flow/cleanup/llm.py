"""Minimal Ollama client. Talks only to a local server (127.0.0.1 / localhost)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:7b-instruct"
FALLBACK_MODEL = "qwen2.5:3b"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LlmError(RuntimeError):
    """Any failure talking to the LLM (down, timeout, bad response)."""


class OllamaClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        fallback: str = FALLBACK_MODEL,
        host: str = "http://127.0.0.1:11434",
        timeout_s: float = 8.0,
        keep_alive: str = "30m",
    ) -> None:
        if urlparse(host).hostname not in LOCAL_HOSTS:
            raise ValueError("privacy: the LLM host must be local (127.0.0.1 or localhost)")
        self.model = model
        self.fallback = fallback
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.keep_alive = keep_alive
        self._active_model: str | None = None
        self._down_until = 0.0
        self.last_used = 0.0  # monotonic time of the last chat request

    # -- plumbing -----------------------------------------------------------------------
    def _request(self, path: str, payload: dict | None, timeout: float) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.host + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local only
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise LlmError(f"{path}: {e}") from e

    # -- status -------------------------------------------------------------------------
    def available(self) -> bool:
        """True if the server answers. A failure is remembered for 10 s to avoid stalls."""
        if time.monotonic() < self._down_until:
            return False
        try:
            self._request("/api/version", None, 0.7)
            return True
        except LlmError:
            self._down_until = time.monotonic() + 10
            return False

    def installed_models(self) -> list[str]:
        try:
            tags = self._request("/api/tags", None, 2.0)
        except LlmError:
            return []
        return [m["name"] for m in tags.get("models", [])]

    def resolve_model(self) -> str | None:
        """The configured model if installed, else the fallback, else None."""
        if self._active_model:
            return self._active_model
        installed = self.installed_models()
        for cand in (self.model, self.fallback):
            if cand in installed or (":" not in cand and f"{cand}:latest" in installed):
                self._active_model = cand
                return cand
        return None

    # -- inference ----------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        timeout_s: float | None = None,
    ) -> str:
        model = self.resolve_model()
        if model is None:
            raise LlmError("no usable model installed")
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 4096},
        }
        self.last_used = time.monotonic()
        out = self._request("/api/chat", payload, timeout_s or self.timeout_s)
        self.last_used = time.monotonic()
        content = out.get("message", {}).get("content")
        if not isinstance(content, str):
            raise LlmError("malformed response")
        return content.strip()

    def warm_up(self) -> bool:
        """Load the model into memory so the first real dictation is fast."""
        if not self.available():
            return False
        try:
            self.chat([{"role": "user", "content": "ok"}], max_tokens=1, timeout_s=60)
            return True
        except LlmError:
            log.warning("LLM warm-up failed", exc_info=True)
            return False
