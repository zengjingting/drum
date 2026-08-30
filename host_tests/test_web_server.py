from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any

from eval.easyinput_eval.providers import (
    Availability,
    GenerationSettings,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
)
from web_server import MODEL_ID, PatternService, make_handler


def valid_pattern() -> dict[str, Any]:
    return {
        "schemaVersion": "easyinput.pattern.v1",
        "name": "Test Groove",
        "style": "Rock",
        "bpm": 120,
        "tracks": {
            "kick": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            "snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            "closed_hat": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
            "open_hat": [0] * 16,
            "clap": [0] * 16,
            "rim": [0] * 16,
        },
        "designNote": "Test-only response.",
    }


class SequenceAdapter(ProviderAdapter):
    provider_id = "deepseek"
    requested_model = MODEL_ID
    deployment = "test"
    schema_mode = "json_object"
    thinking_mode = "disabled"

    def __init__(
        self,
        outputs: list[str] | None = None,
        *,
        available: bool = True,
        provider_error: str | None = None,
    ) -> None:
        self.outputs = list(outputs or [])
        self.is_available = available
        self.provider_error = provider_error
        self.calls = 0

    def availability(self) -> Availability:
        return Availability(self.is_available)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        del messages, output_schema, settings
        self.calls += 1
        if self.provider_error:
            raise ProviderError(self.provider_error)
        raw_output = self.outputs.pop(0)
        return ProviderResponse(
            raw_output=raw_output,
            response_reported_model=MODEL_ID,
            first_token_latency_ms=10,
            complete_response_latency_ms=20,
            response_metadata={},
        )


class ApiServer:
    def __init__(self, service: PatternService) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "ApiServer":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def request(
        self, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        try:
            response = urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        with response:
            return response.status, json.loads(response.read().decode("utf-8"))


class PatternServiceApiTests(unittest.TestCase):
    def test_valid_first_response_returns_pattern_and_firmware_masks(self) -> None:
        adapter = SequenceAdapter([json.dumps(valid_pattern())])
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/generate", {"prompt": "生成一个基础摇滚鼓点"}
            )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["masks"], [0x1111, 0x1010, 0x5555, 0, 0, 0])
        self.assertTrue(payload["firstPass"]["valid"])
        self.assertFalse(payload["repairAttempted"])
        self.assertEqual(adapter.calls, 1)

    def test_invalid_first_response_gets_exactly_one_repair(self) -> None:
        invalid = json.dumps({"schemaVersion": "wrong"})
        adapter = SequenceAdapter([invalid, json.dumps(valid_pattern())])
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/generate", {"prompt": "生成一个基础摇滚鼓点"}
            )
        self.assertEqual(status, 200)
        self.assertFalse(payload["firstPass"]["valid"])
        self.assertTrue(payload["firstPass"]["errors"])
        self.assertTrue(payload["repairAttempted"])
        self.assertEqual(adapter.calls, 2)

    def test_failed_repair_returns_safe_validation_error_without_raw_output(self) -> None:
        secret_raw = "RAW_MODEL_OUTPUT_MUST_NOT_LEAK"
        adapter = SequenceAdapter([secret_raw, secret_raw])
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/generate", {"prompt": "生成一个鼓点"}
            )
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["type"], "validation_error")
        self.assertNotIn(secret_raw, encoded)
        self.assertEqual(adapter.calls, 2)

    def test_provider_error_does_not_leak_provider_details(self) -> None:
        secret = "PRIVATE_PROVIDER_TEST_VALUE"
        adapter = SequenceAdapter(provider_error=f"provider rejected {secret}")
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/generate", {"prompt": "生成一个鼓点"}
            )
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"]["type"], "model_error")
        self.assertNotIn(secret, json.dumps(payload))

    def test_unconfigured_service_and_invalid_prompt_are_distinguished(self) -> None:
        adapter = SequenceAdapter(available=False)
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/generate", {"prompt": "生成一个鼓点"}
            )
            bad_status, bad_payload = api.request(
                "/api/pattern/generate", {"prompt": 123}
            )
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["type"], "configuration_error")
        self.assertEqual(bad_status, 400)
        self.assertEqual(bad_payload["error"]["type"], "request_error")

    def test_health_reports_model_and_thinking_mode(self) -> None:
        adapter = SequenceAdapter([json.dumps(valid_pattern())])
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["thinkingMode"], "disabled")


if __name__ == "__main__":
    unittest.main()
