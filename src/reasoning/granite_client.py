"""GraniteClient — thin HTTP wrapper for IBM Granite / watsonx.ai text generation.

Responsibilities
----------------
- POST to the Granite /v1/text/generation endpoint.
- Support IAM token exchange when standard IBM Cloud API keys are provided.
- Raise GraniteUnavailable on any network, timeout, or HTTP error.
- Never interpret the response — return raw generated text to the caller.
- Read credentials from environment variables / .env file so no secrets appear in code.

Environment variables
---------------------
GRANITE_API_URL    Base URL, e.g. https://us-south.ml.cloud.ibm.com
GRANITE_API_KEY    IBM Cloud / watsonx API key
GRANITE_MODEL_ID   Model ID (default: ibm/granite-3-8b-instruct)
WATSONX_PROJECT_ID Optional watsonx project GUID
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
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


class GraniteUnavailable(RuntimeError):
    """Raised when Granite cannot be reached or returns a non-200 response.

    Callers should catch this and activate the deterministic fallback path.
    """


@dataclass
class GraniteConfig:
    """Runtime configuration for the Granite client.

    Reads from environment variables by default so secrets never appear in
    source code. Pass explicit values only in tests.
    """

    api_url: str = field(
        default_factory=lambda: os.getenv(
            "GRANITE_API_URL", "https://us-south.ml.cloud.ibm.com"
        )
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("GRANITE_API_KEY", "")
    )
    model_id: str = field(
        default_factory=lambda: os.getenv(
            "GRANITE_MODEL_ID", "ibm/granite-3-8b-instruct"
        )
    )
    project_id: str = field(
        default_factory=lambda: os.getenv(
            "WATSONX_PROJECT_ID", os.getenv("GRANITE_PROJECT_ID", "")
        )
    )
    timeout_seconds: int = 30
    max_new_tokens: int = 512
    temperature: float = 0.0   # deterministic output — no sampling


class GraniteClient:
    """HTTP client for IBM Granite text generation."""

    def __init__(self, config: GraniteConfig | None = None) -> None:
        self._cfg = config or GraniteConfig()
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_auth_header(self) -> str:
        key = self._cfg.api_key.strip()
        if key.startswith("Bearer ") or key.startswith("ZenApiKey "):
            return key

        now = time.time()
        if self._cached_token and now < self._token_expires_at:
            return f"Bearer {self._cached_token}"

        # Attempt IAM token exchange for IBM Cloud API keys
        try:
            iam_url = "https://iam.cloud.ibm.com/identity/token"
            data = urllib.parse.urlencode({
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": key,
            }).encode("utf-8")
            req = urllib.request.Request(
                iam_url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "FlowShield/2.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)
                if access_token:
                    self._cached_token = access_token
                    self._token_expires_at = now + expires_in - 120
                    return f"Bearer {access_token}"
        except Exception:
            pass

        return f"Bearer {key}"

    def generate(self, prompt: str) -> str:
        """Send ``prompt`` to Granite and return the generated text.

        Raises
        ------
        GraniteUnavailable
            On any network error, timeout, missing API key, or non-200 HTTP status.
        """
        if not self._cfg.api_key:
            raise GraniteUnavailable(
                "GRANITE_API_KEY is not set. "
                "Set the environment variable or pass GraniteConfig explicitly."
            )

        url = (
            f"{self._cfg.api_url.rstrip('/')}"
            f"/ml/v1/text/generation?version=2023-05-29"
        )
        payload_dict: dict = {
            "model_id": self._cfg.model_id,
            "input": prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": self._cfg.max_new_tokens,
                "temperature": self._cfg.temperature,
                "stop_sequences": ["<|end|>"],
            },
        }
        if self._cfg.project_id:
            payload_dict["project_id"] = self._cfg.project_id

        body = json.dumps(payload_dict).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._get_auth_header(),
                "Accept": "application/json",
                "User-Agent": "FlowShield/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise GraniteUnavailable(
                f"Granite returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise GraniteUnavailable(
                f"Granite unreachable: {exc}"
            ) from exc

        try:
            payload = json.loads(raw)
            return payload["results"][0]["generated_text"].strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GraniteUnavailable(
                f"Unexpected Granite response format: {raw[:200]}"
            ) from exc
