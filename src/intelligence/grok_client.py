"""GrokClient — server-side HTTP client for xAI Grok / Groq Cloud OpenAI-compatible API.

Responsibilities:
- POST to OpenAI-compatible /chat/completions endpoint.
- Read credentials strictly from server environment variables / .env file.
- Support xAI Grok (https://api.x.ai/v1) and Groq Cloud (https://api.groq.com/openai/v1).
- Raise GrokUnavailable on timeout, connection failure, non-200 status, or empty key.
- Never expose the API key to client or logs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


def _load_env_file() -> None:
    """Load variables from .env into os.environ if not already defined."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]
    for env_path in candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:
                pass


_load_env_file()


class GrokUnavailable(RuntimeError):
    """Raised when LLM API is unreachable, disabled, or fails."""


def _resolve_default_url(api_key: str) -> str:
    explicit = os.getenv("GROK_API_URL") or os.getenv("GROQ_API_URL")
    if explicit:
        return explicit
    if api_key.startswith("gsk_"):
        return "https://api.groq.com/openai/v1"
    return "https://api.x.ai/v1"


def _resolve_default_model(api_key: str) -> str:
    explicit = os.getenv("GROK_MODEL_ID") or os.getenv("GROK_MODEL")
    if explicit:
        return explicit
    if api_key.startswith("gsk_"):
        return "openai/gpt-oss-120b"
    return "grok-2-latest"


@dataclass
class GrokConfig:
    """Runtime configuration for Grok / Groq API client."""

    api_key: str = field(
        default_factory=lambda: (
            os.getenv("GROK_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("XAI_API_KEY", "")
        )
    )
    api_url: str = field(default="")
    model_id: str = field(default="")
    timeout_seconds: int = 15
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if not self.api_url:
            self.api_url = _resolve_default_url(self.api_key)
        if not self.model_id:
            self.model_id = _resolve_default_model(self.api_key)


class GrokClient:
    """Server-side client for Grok / Groq chat completions."""

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
        """Send chat completion request and return the assistant response.

        Raises:
            GrokUnavailable: on any network error, HTTP error, timeout, or missing key.
        """
        if not self.is_configured:
            raise GrokUnavailable("GROK_API_KEY / GROQ_API_KEY / XAI_API_KEY is not set.")

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
                "User-Agent": "FlowShield/2.0 (Urban Flood Emergency Platform)",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise GrokUnavailable(f"LLM API HTTP error {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise GrokUnavailable(f"LLM API unreachable: {exc}") from exc

        try:
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GrokUnavailable(f"Malformed LLM API response: {raw[:200]}") from exc
