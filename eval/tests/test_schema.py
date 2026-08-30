import copy
import json
import unittest

from eval.easyinput_eval.cases import build_request, load_benchmark_cases
from eval.easyinput_eval.constants import PATTERN_SCHEMA_PATH, REQUEST_SCHEMA_PATH
from eval.easyinput_eval.validation import validate_pattern, validate_request
from eval.tests.helpers import passing_pattern


class SchemaContractTests(unittest.TestCase):
    def test_schema_documents_are_draft_2020_12_json(self):
        for path in (PATTERN_SCHEMA_PATH, REQUEST_SCHEMA_PATH):
            with self.subTest(path=path):
                with path.open("r", encoding="utf-8") as handle:
                    schema = json.load(handle)
                self.assertEqual(
                    schema["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )

    def test_all_six_benchmark_requests_match_runtime_contract(self):
        cases = load_benchmark_cases()
        self.assertEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case["caseId"]):
                result = validate_request(build_request(case))
                self.assertTrue(result.schema_valid, result.errors_as_dicts())

    def test_valid_pattern_passes(self):
        result = validate_pattern(passing_pattern("G-HOUSE"))
        self.assertTrue(result.schema_valid, result.errors_as_dicts())

    def test_unknown_sample_field_is_rejected(self):
        pattern = passing_pattern("G-HOUSE")
        pattern["sample"] = "kick.wav"
        result = validate_pattern(pattern)
        self.assertFalse(result.schema_valid)
        self.assertIn("additional_property", {issue.code for issue in result.issues})

    def test_boolean_step_is_not_accepted_as_integer(self):
        pattern = passing_pattern("G-HOUSE")
        pattern["tracks"]["kick"][0] = True
        result = validate_pattern(pattern)
        self.assertFalse(result.schema_valid)
        self.assertIn("step_value", {issue.code for issue in result.issues})

    def test_empty_pattern_is_rejected(self):
        pattern = passing_pattern("G-HOUSE")
        for track in pattern["tracks"].values():
            track[:] = [0] * 16
        result = validate_pattern(pattern)
        self.assertFalse(result.schema_valid)
        self.assertIn("empty_pattern", {issue.code for issue in result.issues})

    def test_malformed_track_returns_errors_instead_of_crashing(self):
        pattern = passing_pattern("G-HOUSE")
        pattern["tracks"]["kick"] = None
        result = validate_pattern(pattern)
        self.assertFalse(result.schema_valid)
        self.assertIn("track_length", {issue.code for issue in result.issues})

    def test_generate_request_cannot_include_edit_policy(self):
        request = build_request(load_benchmark_cases()[0])
        request["editPolicy"] = {"mutableFields": [], "immutableFields": []}
        result = validate_request(request)
        self.assertFalse(result.schema_valid)
        self.assertIn("generate_policy", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
