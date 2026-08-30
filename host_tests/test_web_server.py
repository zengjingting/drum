from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eval.easyinput_eval.providers import (
    Availability,
    GenerationSettings,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
)
from web_server import (
    MODEL_ID,
    PatternService,
    RecordingTraceStore,
    _load_local_environment,
    make_handler,
)


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


def explanation_request() -> dict[str, Any]:
    pattern = valid_pattern()
    return {
        "bpm": pattern["bpm"],
        "tracks": pattern["tracks"],
        "approximateQuantization": True,
    }


def valid_explanation() -> dict[str, Any]:
    return {
        "schemaVersion": "easyinput.pattern.explanation.v1",
        "summary": "这个 Pattern 更接近基础 Rock 律动。",
        "styleCandidates": [
            {"style": "Rock", "confidence": "high"},
            {"style": "Pop", "confidence": "medium"},
        ],
        "evidence": [
            {
                "track": "snare",
                "steps": [5, 13],
                "reason": "军鼓落在第二和第四拍，形成清晰反拍。",
            },
            {
                "track": "closed_hat",
                "steps": [1, 3, 5, 7, 9, 11, 13, 15],
                "reason": "闭镲保持稳定八分音符骨架。",
            },
        ],
        "suggestion": "可以移动一个底鼓落点来增加切分感。",
        "limitations": "只依据单小节鼓点，不能判断完整歌曲流派。",
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
    def __init__(
        self,
        service: PatternService,
        trace_store: RecordingTraceStore | None = None,
    ) -> None:
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(service, trace_store=trace_store),
        )
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


class LocalEnvironmentTests(unittest.TestCase):
    def test_local_environment_loads_missing_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text(
                "# local-only defaults\nDEEPSEEK_API_KEY=test-local-key\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                _load_local_environment(path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "test-local-key")

    def test_process_environment_overrides_local_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text(
                "DEEPSEEK_API_KEY=file-value-must-not-win\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"DEEPSEEK_API_KEY": "process-value"}, clear=True
            ):
                _load_local_environment(path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "process-value")

    def test_invalid_local_environment_line_does_not_echo_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("INVALID KEY=secret-must-not-leak\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, r"\.env\.local:1") as error:
                _load_local_environment(path)
            self.assertNotIn("secret-must-not-leak", str(error.exception))


class PatternServiceApiTests(unittest.TestCase):
    def test_recording_trace_round_trip_and_sensitive_field_rejection(self) -> None:
        adapter = SequenceAdapter([json.dumps(valid_pattern())])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording-trace.ndjson"
            trace_store = RecordingTraceStore(path)
            with ApiServer(PatternService(adapter=adapter), trace_store) as api:
                event = {
                    "sessionId": "recording-test",
                    "sequence": 0,
                    "stage": "pad_received",
                    "clientTimeMs": 123456,
                    "payload": {
                        "event": 7,
                        "track": 2,
                        "frame": 48000,
                        "source": "hardware",
                    },
                }
                post_status, post_payload = api.request(
                    "/api/debug/recording-trace", event
                )
                get_status, get_payload = api.request(
                    "/api/debug/recording-trace?sessionId=recording-test"
                )
                bad_status, bad_payload = api.request(
                    "/api/debug/recording-trace",
                    {
                        **event,
                        "sequence": 1,
                        "payload": {"apiKey": "must-not-be-stored"},
                    },
                )

            self.assertEqual(post_status, 200)
            self.assertTrue(post_payload["ok"])
            self.assertEqual(get_status, 200)
            self.assertEqual(len(get_payload["events"]), 1)
            self.assertEqual(get_payload["events"][0]["stage"], "pad_received")
            self.assertEqual(get_payload["events"][0]["payload"]["track"], 2)
            self.assertEqual(bad_status, 400)
            self.assertEqual(bad_payload["error"]["type"], "request_error")
            self.assertNotIn("must-not-be-stored", path.read_text(encoding="utf-8"))

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

    def test_explain_returns_features_and_evidence_checked_output(self) -> None:
        adapter = SequenceAdapter([json.dumps(valid_explanation())])
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/explain", {"pattern": explanation_request()}
            )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["explanation"]["styleCandidates"][0]["style"], "Rock")
        self.assertEqual(payload["features"]["snareBackbeatSteps"], [5, 13])
        self.assertTrue(payload["firstPass"]["valid"])
        self.assertEqual(adapter.calls, 1)

    def test_explain_repairs_evidence_that_cites_inactive_step(self) -> None:
        invalid = valid_explanation()
        invalid["evidence"][0]["steps"] = [2]
        adapter = SequenceAdapter(
            [json.dumps(invalid), json.dumps(valid_explanation())]
        )
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/explain", {"pattern": explanation_request()}
            )
        self.assertEqual(status, 200)
        self.assertFalse(payload["firstPass"]["valid"])
        self.assertTrue(payload["repairAttempted"])
        self.assertEqual(adapter.calls, 2)

    def test_explain_repairs_english_user_visible_copy(self) -> None:
        english = json.loads(json.dumps(valid_explanation()))
        english["summary"] = "This is a basic rock groove."
        english["evidence"][0]["reason"] = "The snare lands on the backbeat."
        english["suggestion"] = "Move one kick to add syncopation."
        english["limitations"] = "One bar is not enough to identify a full song."
        adapter = SequenceAdapter(
            [json.dumps(english), json.dumps(valid_explanation())]
        )
        with ApiServer(PatternService(adapter=adapter)) as api:
            status, payload = api.request(
                "/api/pattern/explain", {"pattern": explanation_request()}
            )
        self.assertEqual(status, 200)
        self.assertFalse(payload["firstPass"]["valid"])
        self.assertTrue(payload["repairAttempted"])
        self.assertEqual(adapter.calls, 2)
        self.assertIn("这个", payload["explanation"]["summary"])

    def test_explain_rejects_empty_or_malformed_pattern(self) -> None:
        adapter = SequenceAdapter([json.dumps(valid_explanation())])
        empty = explanation_request()
        empty["tracks"] = {key: [0] * 16 for key in empty["tracks"]}
        with ApiServer(PatternService(adapter=adapter)) as api:
            empty_status, empty_payload = api.request(
                "/api/pattern/explain", {"pattern": empty}
            )
            malformed_status, malformed_payload = api.request(
                "/api/pattern/explain", {"pattern": {"bpm": 120}}
            )
        self.assertEqual(empty_status, 400)
        self.assertEqual(empty_payload["error"]["type"], "request_error")
        self.assertEqual(malformed_status, 400)
        self.assertEqual(malformed_payload["error"]["type"], "request_error")
        self.assertEqual(adapter.calls, 0)


if __name__ == "__main__":
    unittest.main()
