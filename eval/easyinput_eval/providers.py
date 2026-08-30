from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """A real provider call failed and must be recorded as an error, not a pass."""


def _redact_secrets(value: str) -> str:
    redacted = value
    for secret_name in ("ZHIPUAI_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.environ.get(secret_name)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.6
    top_p: float = 0.9
    max_output_tokens: int = 1024
    timeout_seconds: float = 120.0


@dataclass
class ProviderResponse:
    raw_output: str
    response_reported_model: str | None
    first_token_latency_ms: int | None
    complete_response_latency_ms: int
    response_metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(ABC):
    provider_id: str
    requested_model: str
    deployment: str
    schema_mode: str
    thinking_mode: str
    unsupported_parameters: tuple[str, ...] = ()
    documented_model_version: str | None = None

    @abstractmethod
    def availability(self) -> Availability:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        raise NotImplementedError


def _request_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> urllib.response.addinfourl:
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ProviderError(f"HTTP {exc.code} from provider: {_redact_secrets(body)}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"provider connection failed: {exc.reason}") from exc


class OllamaAdapter(ProviderAdapter):
    provider_id = "ollama"
    deployment = "local_ollama"
    schema_mode = "json_schema"
    thinking_mode = "disabled"

    def __init__(
        self,
        model: str = "qwen3.5:2b",
        base_url: str | None = None,
    ) -> None:
        self.requested_model = model
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")

    def availability(self) -> Availability:
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                payload = json.load(response)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            return Availability(False, f"Ollama is unavailable: {exc}")
        model_names = {
            item.get("name")
            for item in payload.get("models", [])
            if isinstance(item, dict) and item.get("name")
        }
        if self.requested_model not in model_names:
            return Availability(
                False,
                f"Ollama model {self.requested_model!r} is not installed; available={sorted(model_names)}",
            )
        return Availability(True)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        payload = {
            "model": self.requested_model,
            "messages": messages,
            "stream": True,
            "think": False,
            "format": output_schema,
            "options": {
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "num_predict": settings.max_output_tokens,
            },
        }
        started = time.perf_counter()
        chunks: list[str] = []
        first_token_latency_ms: int | None = None
        resolved_model: str | None = None
        final_metadata: dict[str, Any] = {}
        with _request_json(
            f"{self.base_url}/api/chat",
            payload,
            timeout=settings.timeout_seconds,
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"invalid Ollama stream event: {line[:500]}") from exc
                if event.get("error"):
                    raise ProviderError(f"Ollama error: {event['error']}")
                resolved_model = event.get("model") or resolved_model
                content = event.get("message", {}).get("content", "")
                if content:
                    if first_token_latency_ms is None:
                        first_token_latency_ms = round((time.perf_counter() - started) * 1000)
                    chunks.append(content)
                if event.get("done"):
                    final_metadata = {
                        key: event.get(key)
                        for key in (
                            "total_duration",
                            "load_duration",
                            "prompt_eval_count",
                            "prompt_eval_duration",
                            "eval_count",
                            "eval_duration",
                        )
                        if key in event
                    }
        complete_ms = round((time.perf_counter() - started) * 1000)
        raw_output = "".join(chunks)
        if not raw_output:
            raise ProviderError("Ollama completed without model output")
        return ProviderResponse(
            raw_output=raw_output,
            response_reported_model=resolved_model,
            first_token_latency_ms=first_token_latency_ms,
            complete_response_latency_ms=complete_ms,
            response_metadata=final_metadata,
        )


class OpenAICompatibleAdapter(ProviderAdapter):
    schema_mode = "json_object"

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        endpoint: str,
        api_key_env: str,
        deployment: str,
        thinking_mode: str,
        extra_payload: dict[str, Any] | None = None,
        unsupported_parameters: tuple[str, ...] = (),
    ) -> None:
        self.provider_id = provider_id
        self.requested_model = model
        self.endpoint = endpoint
        self.api_key_env = api_key_env
        self.deployment = deployment
        self.thinking_mode = thinking_mode
        self.extra_payload = extra_payload or {}
        self.unsupported_parameters = unsupported_parameters

    def availability(self) -> Availability:
        if not os.environ.get(self.api_key_env):
            return Availability(
                False,
                f"{self.api_key_env} is not set; {self.provider_id} must be recorded as skipped",
            )
        return Availability(True)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderError(f"{self.api_key_env} is not set")
        payload: dict[str, Any] = {
            "model": self.requested_model,
            "messages": messages,
            "stream": True,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "max_tokens": settings.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        payload.update(self.extra_payload)
        started = time.perf_counter()
        chunks: list[str] = []
        first_token_latency_ms: int | None = None
        resolved_model: str | None = None
        final_metadata: dict[str, Any] = {}
        headers = {"Authorization": f"Bearer {api_key}"}
        with _request_json(
            self.endpoint,
            payload,
            headers=headers,
            timeout=settings.timeout_seconds,
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"invalid SSE event: {line[:500]}") from exc
                if event.get("error"):
                    raise ProviderError(
                        f"{self.provider_id} error: {_redact_secrets(str(event['error']))}"
                    )
                resolved_model = event.get("model") or resolved_model
                choices = event.get("choices") or []
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content") or ""
                    if content:
                        if first_token_latency_ms is None:
                            first_token_latency_ms = round((time.perf_counter() - started) * 1000)
                        chunks.append(content)
                if event.get("usage"):
                    final_metadata["usage"] = event["usage"]
        complete_ms = round((time.perf_counter() - started) * 1000)
        raw_output = "".join(chunks)
        if not raw_output:
            raise ProviderError(f"{self.provider_id} completed without model output")
        return ProviderResponse(
            raw_output=raw_output,
            response_reported_model=resolved_model,
            first_token_latency_ms=first_token_latency_ms,
            complete_response_latency_ms=complete_ms,
            response_metadata=final_metadata,
        )


def default_adapters() -> dict[str, ProviderAdapter]:
    adapters: dict[str, ProviderAdapter] = {
        "ollama": OllamaAdapter(),
        "zhipu": OpenAICompatibleAdapter(
            provider_id="zhipu",
            model="glm-5.3-flash",
            endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            api_key_env="ZHIPUAI_API_KEY",
            deployment="cloud_api",
            thinking_mode="enabled_low",
            extra_payload={
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
            },
        ),
        "deepseek": OpenAICompatibleAdapter(
            provider_id="deepseek",
            model="deepseek-v4-flash",
            endpoint="https://api.deepseek.com/chat/completions",
            api_key_env="DEEPSEEK_API_KEY",
            deployment="cloud_api",
            thinking_mode="disabled",
            extra_payload={"thinking": {"type": "disabled"}},
        ),
    }
    adapters["deepseek"].documented_model_version = "DeepSeek-V4-Flash-0731"
    return adapters
