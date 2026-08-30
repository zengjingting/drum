import copy
import unittest

from eval.easyinput_eval.scoring import EXPECTED_CASE_IDS, summarize_records


CONSTRAINT_IDS = {
    "G-HOUSE": ("bpm-124", "four-on-floor"),
    "G-FUNK": ("bpm-105", "backbeat", "kick-density", "kick-syncopation"),
    "G-COUNTRY": ("bpm-120", "backbeat", "eighth-note-hat"),
    "E-HOUSE": ("close-hat-off", "open-hat-on"),
    "E-FUNK": ("kick-reduced", "kick-syncopation-retained"),
    "E-COUNTRY": ("fill-density", "rim-in-fill"),
}


def make_model_records(
    provider_id,
    requested_model,
    latencies,
    *,
    constraint_passes=None,
    edit_passes=None,
    repair_failed=False,
):
    constraint_passes = constraint_passes or {
        case_id: [True] * len(ids) for case_id, ids in CONSTRAINT_IDS.items()
    }
    edit_passes = edit_passes or {
        "E-HOUSE": True,
        "E-FUNK": True,
        "E-COUNTRY": True,
    }
    records = []
    for case_id, latency in zip(EXPECTED_CASE_IDS, latencies, strict=True):
        first_constraints_valid = all(constraint_passes[case_id])
        edit_valid = edit_passes.get(case_id, True)
        first_valid = first_constraints_valid and edit_valid
        records.append(
            {
                "runId": f"run-{provider_id}-{case_id}",
                "providerId": provider_id,
                "requestedModel": requested_model,
                "caseId": case_id,
                "firstPassJsonParsed": True,
                "firstPassSchemaValid": True,
                "firstPassConstraintsValid": first_constraints_valid,
                "firstPassEditPolicyValid": edit_valid,
                "firstPassValid": first_valid,
                "constraintResults": [
                    {
                        "constraintId": constraint_id,
                        "passed": passed,
                        "message": "pass" if passed else "synthetic failure",
                    }
                    for constraint_id, passed in zip(
                        CONSTRAINT_IDS[case_id], constraint_passes[case_id], strict=True
                    )
                ],
                "repairAttempted": repair_failed,
                "repairValid": False if repair_failed else None,
                "maskConversionValid": True,
                "hardwareEligible": first_valid,
                "hardwareAck": None,
                "firstSchemaValidPatternLatencyMs": latency,
            }
        )
    return records


class ScoringTests(unittest.TestCase):
    def test_summarizes_the_three_current_result_shapes(self):
        qwen_constraints = {
            "G-HOUSE": [True, False],
            "G-FUNK": [True, True, True, False],
            "G-COUNTRY": [True, False, False],
            "E-HOUSE": [True, False],
            "E-FUNK": [True, False],
            "E-COUNTRY": [True, True],
        }
        records = make_model_records(
            "ollama",
            "qwen3.5:2b",
            [10371, 7497, 8091, 7142, 6372, 7227],
            constraint_passes=qwen_constraints,
            edit_passes={"E-HOUSE": True, "E-FUNK": False, "E-COUNTRY": False},
            repair_failed=True,
        )
        records += make_model_records(
            "zhipu",
            "glm-5.3-flash",
            [9407, 8763, 6427, 4148, 8588, 4007],
        )
        records += make_model_records(
            "deepseek",
            "deepseek-v4-flash",
            [2050, 2459, 1963, 2191, 3052, 1736],
        )

        summary = summarize_records(records)
        by_provider = {model["providerId"]: model for model in summary["models"]}

        qwen = by_provider["ollama"]
        self.assertEqual(qwen["scores"]["structure"]["score"], 20.0)
        self.assertEqual(qwen["scores"]["instruction"]["passedItems"], 10)
        self.assertEqual(qwen["scores"]["instruction"]["score"], 16.667)
        self.assertEqual(qwen["scores"]["latency"]["medianMs"], 7362.0)
        self.assertEqual(qwen["scores"]["latency"]["score"], 0)
        self.assertFalse(qwen["hardGates"]["passed"])
        self.assertEqual(qwen["scores"]["automaticSubtotal"]["score"], 36.667)

        zhipu = by_provider["zhipu"]
        self.assertEqual(zhipu["scores"]["instruction"]["score"], 30.0)
        self.assertEqual(zhipu["scores"]["latency"]["medianMs"], 7507.5)
        self.assertEqual(zhipu["scores"]["latency"]["score"], 3)
        self.assertTrue(zhipu["hardGates"]["passed"])
        self.assertEqual(zhipu["scores"]["automaticSubtotal"]["score"], 53.0)

        deepseek = by_provider["deepseek"]
        self.assertEqual(deepseek["scores"]["latency"]["medianMs"], 2120.5)
        self.assertEqual(deepseek["scores"]["latency"]["score"], 8)
        self.assertEqual(deepseek["scores"]["automaticSubtotal"]["score"], 58.0)
        self.assertIsNone(deepseek["scores"]["blindListening"]["score"])
        self.assertIsNone(deepseek["scores"]["total"]["score"])

    def test_external_ack_artifact_scores_acks_and_preserves_firmware_gap(self):
        records = make_model_records(
            "deepseek",
            "deepseek-v4-flash",
            [1000, 1100, 1200, 1300, 1400, 1500],
        )
        evidence = {
            "freezeId": "formal-test",
            "observedAt": "2026-08-30T00:00:00Z",
            "deviceFirmwareCommitVerified": False,
            "deviceFirmwareCommitVerificationGap": "STATE has no firmware digest",
            "results": [
                {"runId": record["runId"], "patternAck": True} for record in records
            ],
        }

        summary = summarize_records(records, evidence)
        model = summary["models"][0]

        self.assertIn(
            "A PATTERN ACK proves protocol acceptance only; it does not verify the flashed firmware commit.",
            summary["assumptions"],
        )
        self.assertEqual(model["scores"]["structure"]["score"], 30.0)
        self.assertEqual(
            model["scores"]["structure"]["components"]["hardwareAck"]["passedCases"],
            6,
        )
        self.assertEqual(model["scores"]["automaticSubtotal"]["score"], 70.0)
        self.assertTrue(model["hardGates"]["noInvalidHardwareDispatch"]["passed"])
        self.assertEqual(
            summary["auditGaps"],
            [
                {
                    "code": "device_firmware_commit_unverified",
                    "message": "STATE has no firmware digest",
                }
            ],
        )

    def test_invalid_pattern_with_ack_fails_dispatch_gate(self):
        records = make_model_records(
            "test",
            "model",
            [1000, 1100, 1200, 1300, 1400, 1500],
        )
        records = copy.deepcopy(records)
        records[0]["firstPassValid"] = False
        records[0]["firstPassConstraintsValid"] = False
        records[0]["hardwareEligible"] = False
        records[0]["constraintResults"][0]["passed"] = False
        evidence = {record["runId"]: True for record in records}

        summary = summarize_records(records, evidence)
        model = summary["models"][0]

        self.assertFalse(model["hardGates"]["noInvalidHardwareDispatch"]["passed"])
        self.assertEqual(
            model["hardGates"]["noInvalidHardwareDispatch"]["violationCaseIds"],
            ["G-HOUSE"],
        )
        house = next(item for item in model["caseFailures"] if item["caseId"] == "G-HOUSE")
        self.assertIn(
            "invalid_pattern_hardware_dispatch",
            {item["code"] for item in house["failedItems"]},
        )

    def test_repair_success_keeps_first_pass_deductions_and_missing_latency_null(self):
        records = make_model_records(
            "test",
            "repairing-model",
            [1000, 1100, 1200, 1300, 1400, 1500],
        )
        records = copy.deepcopy(records)
        repaired = records[0]
        repaired["firstPassJsonParsed"] = False
        repaired["firstPassSchemaValid"] = False
        repaired["firstPassValid"] = False
        repaired["constraintResults"] = []
        repaired["repairAttempted"] = True
        repaired["repairValid"] = True
        repaired["firstSchemaValidPatternLatencyMs"] = None

        model = summarize_records(records)["models"][0]

        self.assertTrue(model["hardGates"]["schemaAndFinalValidity"]["passed"])
        self.assertEqual(model["scores"]["structure"]["score"], 17.5)
        self.assertEqual(model["scores"]["instruction"]["totalItems"], 18)
        self.assertEqual(model["scores"]["instruction"]["passedItems"], 16)
        self.assertIsNone(model["scores"]["latency"]["score"])
        self.assertIsNone(model["scores"]["automaticSubtotal"]["score"])


if __name__ == "__main__":
    unittest.main()
