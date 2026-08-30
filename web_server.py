#!/usr/bin/env python3
"""Local-only web server and DeepSeek proxy for the EasyInput drum UI."""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from eval.easyinput_eval.cases import load_benchmark_document
from eval.easyinput_eval.masks import masks_as_firmware_order
from eval.easyinput_eval.prompts import build_initial_messages, build_repair_messages
from eval.easyinput_eval.providers import (
    Availability,
    GenerationSettings,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
    default_adapters,
)
from eval.easyinput_eval.runner import load_output_schema
from eval.easyinput_eval.validation import (
    parse_pattern_json,
    validate_pattern,
    validate_request,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "main" / "web"
MAX_REQUEST_BYTES = 16 * 1024
MODEL_ID = "deepseek-v4-flash"


class PublicApiError(RuntimeError):
    def __init__(self, error_type: str, message: str, status: HTTPStatus) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status = status


def _generate_request(user_prompt: str) -> dict[str, Any]:
    defaults = copy.deepcopy(load_benchmark_document()["requestDefaults"])
    defaults.update(
        {
            "task": "generate",
            "userPrompt": user_prompt,
            "currentPattern": None,
        }
    )
    validation = validate_request(defaults)
    if not validation.schema_valid:
        raise RuntimeError(f"internal request contract is invalid: {validation.errors_as_dicts()}")
    return defaults


def _validate_output(raw_output: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    pattern, parse_issues = parse_pattern_json(raw_output)
    if parse_issues:
        return None, [issue.to_dict() for issue in parse_issues]
    validation = validate_pattern(pattern)
    if not validation.valid:
        return pattern, validation.errors_as_dicts()
    return pattern, []


class PatternService:
    def __init__(
        self,
        adapter: ProviderAdapter | None = None,
        settings: GenerationSettings | None = None,
        *,
        mock_mode: bool = False,
    ) -> None:
        self.adapter = adapter or default_adapters()["deepseek"]
        self.settings = settings or GenerationSettings()
        self.mock_mode = mock_mode
        if self.adapter.requested_model != MODEL_ID and not mock_mode:
            raise ValueError(f"runtime model must be {MODEL_ID}")
        if self.adapter.thinking_mode != "disabled":
            raise ValueError("P0 runtime must keep DeepSeek thinking disabled")

    def health(self) -> dict[str, Any]:
        available = self.adapter.availability().available
        return {
            "ok": True,
            "service": "easyinput-ai-pattern",
            "model": self.adapter.requested_model,
            "thinkingMode": self.adapter.thinking_mode,
            "configured": available,
            "mock": self.mock_mode,
        }

    def generate(self, user_prompt: str) -> dict[str, Any]:
        if not isinstance(user_prompt, str):
            raise PublicApiError(
                "request_error", "prompt 必须是文本。", HTTPStatus.BAD_REQUEST
            )
        prompt = user_prompt.strip()
        if not prompt:
            raise PublicApiError("request_error", "请输入鼓点描述。", HTTPStatus.BAD_REQUEST)
        if len(prompt) > 500:
            raise PublicApiError(
                "request_error", "鼓点描述不能超过 500 个字符。", HTTPStatus.BAD_REQUEST
            )
        if not self.adapter.availability().available:
            raise PublicApiError(
                "configuration_error",
                "本地 AI 服务尚未配置 DEEPSEEK_API_KEY。",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        request = _generate_request(prompt)
        schema = load_output_schema()
        started = time.perf_counter()
        first_response = self._call(
            messages=build_initial_messages(request, schema), output_schema=schema
        )
        first_pattern, first_errors = _validate_output(first_response.raw_output)
        first_valid = not first_errors
        repair_response: ProviderResponse | None = None
        final_pattern = first_pattern
        final_errors = first_errors

        if not first_valid:
            repair_response = self._call(
                messages=build_repair_messages(
                    request,
                    schema,
                    first_response.raw_output,
                    first_errors,
                ),
                output_schema=schema,
            )
            final_pattern, final_errors = _validate_output(repair_response.raw_output)

        if final_pattern is None or final_errors:
            raise PublicApiError(
                "validation_error",
                "模型输出在一次修复后仍未通过硬件 Pattern 校验，请换一种描述重试。",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        masks = masks_as_firmware_order(final_pattern)
        total_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "model": {
                "requested": self.adapter.requested_model,
                "reported": (
                    repair_response.response_reported_model
                    if repair_response is not None
                    else first_response.response_reported_model
                ),
                "thinkingMode": self.adapter.thinking_mode,
                "mock": self.mock_mode,
            },
            "latencyMs": {
                "firstToken": first_response.first_token_latency_ms,
                "firstResponse": first_response.complete_response_latency_ms,
                "repairFirstToken": (
                    repair_response.first_token_latency_ms if repair_response else None
                ),
                "repairResponse": (
                    repair_response.complete_response_latency_ms if repair_response else None
                ),
                "total": total_ms,
            },
            "firstPass": {
                "valid": first_valid,
                "errors": first_errors,
            },
            "repairAttempted": repair_response is not None,
            "pattern": final_pattern,
            "masks": masks,
        }

    def _call(
        self, *, messages: list[dict[str, str]], output_schema: dict[str, Any]
    ) -> ProviderResponse:
        try:
            return self.adapter.generate(
                messages=messages,
                output_schema=output_schema,
                settings=self.settings,
            )
        except ProviderError as exc:
            raise PublicApiError(
                "model_error",
                "DeepSeek 调用失败，请检查网络或稍后重试。",
                HTTPStatus.BAD_GATEWAY,
            ) from exc


class MockDeepSeekAdapter(ProviderAdapter):
    provider_id = "deepseek"
    requested_model = MODEL_ID
    deployment = "local_mock"
    schema_mode = "json_object"
    thinking_mode = "disabled"

    def availability(self) -> Availability:
        return Availability(True)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        del messages, output_schema, settings
        pattern = {
            "schemaVersion": "easyinput.pattern.v1",
            "name": "Mock House",
            "style": "House",
            "bpm": 124,
            "tracks": {
                "kick": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                "snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
                "closed_hat": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
                "open_hat": [0] * 16,
                "clap": [0] * 16,
                "rim": [0] * 16,
            },
            "designNote": "本地 mock 仅用于验证页面状态与串口应用链路。",
        }
        return ProviderResponse(
            raw_output=json.dumps(pattern, ensure_ascii=False),
            response_reported_model="mock-deepseek-v4-flash",
            first_token_latency_ms=20,
            complete_response_latency_ms=40,
            response_metadata={},
        )


def make_handler(service: PatternService, web_root: Path = WEB_ROOT):
    class EasyInputHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/api/health":
                self._write_json(HTTPStatus.OK, service.health())
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != "/api/pattern/generate":
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": {"type": "not_found", "message": "接口不存在。"}},
                )
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                self._write_public_error(
                    PublicApiError(
                        "request_error", "请求大小不合法。", HTTPStatus.BAD_REQUEST
                    )
                )
                return
            try:
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write_public_error(
                    PublicApiError(
                        "request_error", "请求必须是合法 JSON。", HTTPStatus.BAD_REQUEST
                    )
                )
                return
            if not isinstance(body, dict) or set(body) != {"prompt"}:
                self._write_public_error(
                    PublicApiError(
                        "request_error",
                        "请求只能包含 prompt 字段。",
                        HTTPStatus.BAD_REQUEST,
                    )
                )
                return
            try:
                result = service.generate(body.get("prompt", ""))
            except PublicApiError as exc:
                self._write_public_error(exc)
                return
            except Exception:
                self._write_public_error(
                    PublicApiError(
                        "server_error", "本地 AI 服务发生错误。", HTTPStatus.INTERNAL_SERVER_ERROR
                    )
                )
                return
            self._write_json(HTTPStatus.OK, result)

        def _write_public_error(self, exc: PublicApiError) -> None:
            self._write_json(
                exc.status,
                {
                    "ok": False,
                    "error": {"type": exc.error_type, "message": exc.message},
                },
            )

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            # The stdlib access log includes only method/path/status. Request bodies,
            # prompts, model output, and credentials are never logged here.
            super().log_message(format, *args)

    return EasyInputHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyInput local AI web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mock", action="store_true", help="use a local deterministic mock")
    args = parser.parse_args()

    adapter: ProviderAdapter | None = MockDeepSeekAdapter() if args.mock else None
    service = PatternService(adapter=adapter, mock_mode=args.mock)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    mode = "mock" if args.mock else "DeepSeek"
    configured = "yes" if service.health()["configured"] else "no"
    print(
        f"EasyInput web: http://{args.host}:{args.port}/ "
        f"mode={mode} api_configured={configured}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
