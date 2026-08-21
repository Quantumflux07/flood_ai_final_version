"""GrokClient — server-side HTTP client for xAI Grok API.

Responsibilities:
- POST to OpenAI-compatible /chat/completions endpoint.
- Read credentials strictly from server environment variables (GROK_API_KEY / XAI_API_KEY).
- Raise GrokUnavailable on timeout, connection failure, non-200 status, or empty key.
- Never expose the API key to client or logs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class GrokUnavailable(RuntimeError):
    """Raised when Grok API is unreachable, disabled, or fails."""


@dataclass
class GrokConfig:
    """Runtime configuration for Grok API client."""

    api_url: str = field(
        default_factory=lambda: os.getenv("GROK_API_URL", "https://api.x.ai/v1")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY", "")
    )
    model_id: str = field(
        default_factory=lambda: os.getenv("GROK_MODEL_ID")
        or os.getenv("GROK_MODEL", "grok-2-latest")
    )
    timeout_seconds: int = 15
    temperature: float = 0.0


class GrokClient:
    """Server-side client for Grok chat completions."""

    def __init__(self, config: GrokConfig | None = None) -> None:
        self._cfg = config or GrokConfig()

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is present."""
        return bool(self._cfg.api_key and self._cfg.api_key.strip())

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = True,
    ) -> str:
        """Send chat completion request to Grok and return the assistant response.

        Raises:
            GrokUnavailable: on any network error, HTTP error, timeout, or missing key.
        """
        if not self.is_configured:
            raise GrokUnavailable("GROK_API_KEY / XAI_API_KEY is not set.")

        url = f"{self._cfg.api_url.rstrip('/')}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload_dict: dict = {
            "model": self._cfg.model_id,
            "messages": messages,
            "temperature": self._cfg.temperature,
        }
        if json_mode:
            payload_dict["response_format"] = {"type": "json_object"}

        body = json.dumps(payload_dict).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._cfg.api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise GrokUnavailable(f"Grok API HTTP error {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise GrokUnavailable(f"Grok API unreachable: {exc}") from exc

        try:
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GrokUnavailable(f"Malformed Grok API response: {raw[:200]}") from exc
