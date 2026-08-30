import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.easyinput_eval.cases import get_case
from eval.easyinput_eval.cli import FORMAL_CONFIRMATION, main
from eval.easyinput_eval.providers import (
    Availability,
    GenerationSettings,
    ProviderAdapter,
    ProviderResponse,
    _redact_secrets,
    default_adapters,
)
from eval.easyinput_eval.records import JsonlRunStore, make_base_record
from eval.easyinput_eval.runner import run_case
from eval.tests.helpers import passing_pattern


class FakeProvider(ProviderAdapter):
    provider_id = "fake"
    requested_model = "fake-small"
    deployment = "test"
    schema_mode = "json_schema"
    thinking_mode = "disabled"

    def __init__(self, output):
        self.output = output

    def availability(self):
        return Availability(True)

    def generate(self, *, messages, output_schema, settings):
        return ProviderResponse(
            raw_output=self.output,
            response_reported_model="fake-small-v1",
            first_token_latency_ms=2,
            complete_response_latency_ms=3,
        )


class SequencedFakeProvider(FakeProvider):
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.call_count = 0

    def generate(self, *, messages, output_schema, settings):
        output = self.outputs[self.call_count]
        self.call_count += 1
        return ProviderResponse(
            raw_output=output,
            response_reported_model="fake-small-v1",
            first_token_latency_ms=2,
            complete_response_latency_ms=3,
        )


class RecordAndRunnerTests(unittest.TestCase):
    def test_schema_and_constraint_validity_are_recorded_separately(self):
        pattern = passing_pattern("G-HOUSE")
        pattern["tracks"]["kick"][2] = 1
        record = run_case(
            case=get_case("G-HOUSE"),
            adapter=FakeProvider(json.dumps(pattern)),
            run_mode="smoke",
            session_id="separate-validity",
            settings=GenerationSettings(),
            allow_repair=False,
        )
        self.assertEqual(record["status"], "completed")
        self.assertTrue(record["firstPassSchemaValid"])
        self.assertFalse(record["firstPassConstraintsValid"])
        self.assertTrue(record["firstPassEditPolicyValid"])
        self.assertFalse(record["firstPassValid"])
        self.assertTrue(record["maskConversionValid"])
        self.assertFalse(record["hardwareEligible"])

    def test_missing_cloud_key_is_a_skip_not_a_pass(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = default_adapters()["zhipu"]
            record = run_case(
                case=get_case("G-HOUSE"),
                adapter=adapter,
                run_mode="smoke",
                session_id="missing-key",
                settings=GenerationSettings(),
                allow_repair=False,
            )
        self.assertEqual(record["status"], "skipped")
        self.assertIn("ZHIPUAI_API_KEY", record["skipReason"])
        self.assertFalse(record["firstPassValid"])

    def test_one_repair_preserves_first_pass_failure(self):
        valid = passing_pattern("G-HOUSE")
        invalid = dict(valid)
        invalid["sample"] = "not-allowed.wav"
        adapter = SequencedFakeProvider([json.dumps(invalid), json.dumps(valid)])
        record = run_case(
            case=get_case("G-HOUSE"),
            adapter=adapter,
            run_mode="smoke",
            session_id="repair-once",
            settings=GenerationSettings(),
            allow_repair=True,
        )
        self.assertEqual(adapter.call_count, 2)
        self.assertFalse(record["firstPassSchemaValid"])
        self.assertFalse(record["firstPassValid"])
        self.assertTrue(record["repairAttempted"])
        self.assertTrue(record["repairSchemaValid"])
        self.assertTrue(record["repairConstraintsValid"])
        self.assertTrue(record["repairValid"])
        self.assertTrue(record["hardwareEligible"])

    def test_record_store_refuses_mode_mixing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonlRunStore(
                session_id="smoke-session",
                mode="smoke",
                root=Path(temp_dir),
            )
            record = make_base_record(
                run_id="formal-record",
                run_mode="formal",
                session_id="smoke-session",
                case_id="G-HOUSE",
                provider_id="fake",
                requested_model="fake",
                deployment="test",
                schema_mode="json_schema",
                thinking_mode="disabled",
                temperature=0.6,
                top_p=0.9,
                max_output_tokens=600,
                firmware_commit=None,
                web_commit=None,
                asset_manifest_sha256=None,
            )
            with self.assertRaises(ValueError):
                store.append(record)

    def test_record_store_writes_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonlRunStore(
                session_id="smoke-session",
                mode="smoke",
                root=Path(temp_dir),
            )
            record = make_base_record(
                run_id="smoke-record",
                run_mode="smoke",
                session_id="smoke-session",
                case_id="G-HOUSE",
                provider_id="fake",
                requested_model="fake",
                deployment="test",
                schema_mode="json_schema",
                thinking_mode="disabled",
                temperature=0.6,
                top_p=0.9,
                max_output_tokens=600,
                firmware_commit=None,
                web_commit=None,
                asset_manifest_sha256=None,
            )
            path = store.append(record)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["runMode"], "smoke")

    def test_formal_command_is_blocked_without_exact_confirmation(self):
        exit_code = main(
            [
                "formal",
                "--confirm-formal",
                "no",
                "--firmware-commit",
                "abc",
                "--web-commit",
                "abc",
                "--asset-manifest-sha256",
                "abc",
            ]
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(
            FORMAL_CONFIRMATION,
            "RUN_18_CASES_WITH_UP_TO_ONE_REPAIR_EACH",
        )

    def test_default_provider_models_match_frozen_candidates(self):
        adapters = default_adapters()
        self.assertEqual(adapters["ollama"].requested_model, "qwen3.5:2b")
        self.assertEqual(adapters["zhipu"].requested_model, "glm-5.3-flash")
        self.assertEqual(adapters["zhipu"].thinking_mode, "enabled_low")
        self.assertEqual(adapters["zhipu"].extra_payload["reasoning_effort"], "low")
        self.assertEqual(adapters["deepseek"].requested_model, "deepseek-v4-flash")
        self.assertEqual(adapters["deepseek"].thinking_mode, "disabled")
        self.assertEqual(
            adapters["deepseek"].documented_model_version,
            "DeepSeek-V4-Flash-0731",
        )

    def test_secret_redaction_never_echoes_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "do-not-log-this"}, clear=True):
            redacted = _redact_secrets("bad token do-not-log-this")
        self.assertEqual(redacted, "bad token [REDACTED]")


if __name__ == "__main__":
    unittest.main()
