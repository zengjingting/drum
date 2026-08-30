from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


SCORING_VERSION = "easyinput-groove-score.v1"

# These are the 15 pre-registered non-structural constraints. Keeping the IDs
# here makes a missing result a failure instead of silently shrinking the
# denominator.
CASE_CONSTRAINT_IDS: dict[str, tuple[str, ...]] = {
    "G-HOUSE": ("bpm-124", "four-on-floor"),
    "G-FUNK": ("bpm-105", "backbeat", "kick-density", "kick-syncopation"),
    "G-COUNTRY": ("bpm-120", "backbeat", "eighth-note-hat"),
    "E-HOUSE": ("close-hat-off", "open-hat-on"),
    "E-FUNK": ("kick-reduced", "kick-syncopation-retained"),
    "E-COUNTRY": ("fill-density", "rim-in-fill"),
}
EXPECTED_CASE_IDS = tuple(CASE_CONSTRAINT_IDS)
EDIT_CASE_IDS = frozenset(case_id for case_id in EXPECTED_CASE_IDS if case_id.startswith("E-"))
EXPECTED_CONSTRAINT_COUNT = sum(len(ids) for ids in CASE_CONSTRAINT_IDS.values())
EXPECTED_INSTRUCTION_ITEM_COUNT = EXPECTED_CONSTRAINT_COUNT + len(EDIT_CASE_IDS)


def _round_score(value: float) -> float:
    return round(value, 3)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _ack_success(value: Any) -> bool:
    if value is True:
        return True
    if not isinstance(value, Mapping):
        return False
    if "patternAck" in value:
        return value.get("patternAck") is True
    return value.get("type") == "ack" and value.get("command") == "PATTERN"


def _normalize_hardware_acks(
    hardware_acks: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    """Return run-id ACKs, audit metadata, and normalization issues.

    ``hardware_acks`` may be either ``{run_id: ack_value}`` or the immutable
    hardware evidence artifact with a ``results`` array. This helper never
    mutates the supplied object.
    """

    metadata = {
        "provided": hardware_acks is not None,
        "freezeId": None,
        "observedAt": None,
        "deviceFirmwareCommitVerified": None,
        "deviceFirmwareCommitVerificationGap": None,
        "ackEntryCount": 0,
    }
    if hardware_acks is None:
        return {}, metadata, []
    if not isinstance(hardware_acks, Mapping):
        raise TypeError("hardware_acks must be a mapping or None")

    issues: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}
    if "results" not in hardware_acks:
        normalized = {str(run_id): value for run_id, value in hardware_acks.items()}
        metadata["ackEntryCount"] = len(normalized)
        return normalized, metadata, issues

    metadata.update(
        {
            "freezeId": hardware_acks.get("freezeId"),
            "observedAt": hardware_acks.get("observedAt"),
            "deviceFirmwareCommitVerified": hardware_acks.get(
                "deviceFirmwareCommitVerified"
            ),
            "deviceFirmwareCommitVerificationGap": hardware_acks.get(
                "deviceFirmwareCommitVerificationGap"
            ),
        }
    )
    results = hardware_acks.get("results")
    if not isinstance(results, list):
        issues.append(
            {
                "code": "hardware_results_type",
                "message": "hardware evidence results must be an array",
            }
        )
        return normalized, metadata, issues

    seen_run_ids: set[str] = set()
    for index, item in enumerate(results):
        if not isinstance(item, Mapping) or not isinstance(item.get("runId"), str):
            issues.append(
                {
                    "code": "hardware_result_shape",
                    "message": f"hardware result at index {index} has no string runId",
                }
            )
            continue
        run_id = item["runId"]
        if run_id in seen_run_ids:
            issues.append(
                {
                    "code": "duplicate_hardware_run_id",
                    "message": f"hardware evidence repeats runId {run_id}",
                }
            )
            normalized.pop(run_id, None)
            continue
        seen_run_ids.add(run_id)
        if "patternAck" not in item:
            issues.append(
                {
                    "code": "hardware_ack_missing",
                    "message": f"hardware result {run_id} has no patternAck",
                }
            )
            continue
        normalized[run_id] = item["patternAck"]

    metadata["ackEntryCount"] = len(normalized)
    return normalized, metadata, issues


def _effective_ack(record: Mapping[str, Any], ack_by_run_id: Mapping[str, Any]) -> Any:
    run_id = record.get("runId")
    if isinstance(run_id, str) and run_id in ack_by_run_id:
        return ack_by_run_id[run_id]
    return record.get("hardwareAck")


def _final_valid(record: Mapping[str, Any]) -> bool:
    if record.get("firstPassValid") is True:
        return True
    return record.get("repairAttempted") is True and record.get("repairValid") is True


def _component(name: str, passed: int, max_score: int) -> dict[str, Any]:
    return {
        "name": name,
        "passedCases": passed,
        "totalCases": len(EXPECTED_CASE_IDS),
        "score": _round_score(passed / len(EXPECTED_CASE_IDS) * max_score),
        "maxScore": max_score,
    }


def _latency_score(milliseconds: float) -> int:
    if milliseconds <= 2_000:
        return 10
    if milliseconds <= 3_000:
        return 8
    if milliseconds <= 5_000:
        return 6
    if milliseconds <= 8_000:
        return 3
    return 0


def _summarize_model(
    records: list[Mapping[str, Any]],
    *,
    ack_by_run_id: Mapping[str, Any],
) -> dict[str, Any]:
    provider_id = str(records[0].get("providerId"))
    requested_model = str(records[0].get("requestedModel"))
    case_buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    unexpected_case_ids: list[str] = []
    for record in records:
        case_id = record.get("caseId")
        if case_id in CASE_CONSTRAINT_IDS:
            case_buckets[str(case_id)].append(record)
        else:
            unexpected_case_ids.append(str(case_id))

    data_issues: list[dict[str, str]] = []
    for case_id in unexpected_case_ids:
        data_issues.append(
            {
                "code": "unexpected_case",
                "message": f"unexpected caseId {case_id}",
            }
        )

    unique_records: dict[str, Mapping[str, Any] | None] = {}
    for case_id in EXPECTED_CASE_IDS:
        bucket = case_buckets.get(case_id, [])
        if len(bucket) == 1:
            unique_records[case_id] = bucket[0]
        elif not bucket:
            unique_records[case_id] = None
            data_issues.append(
                {
                    "code": "missing_case",
                    "message": f"missing caseId {case_id}",
                }
            )
        else:
            unique_records[case_id] = None
            data_issues.append(
                {
                    "code": "duplicate_case",
                    "message": f"caseId {case_id} occurs {len(bucket)} times",
                }
            )

    instruction_items: list[dict[str, Any]] = []
    case_failures: list[dict[str, Any]] = []
    structure_counts = {"json": 0, "schema": 0, "mask": 0, "ack": 0}
    first_schema_valid_count = 0
    final_valid_count = 0
    invalid_dispatch_cases: list[str] = []
    repair_failure_cases: list[str] = []
    latency_values: list[float] = []
    latency_missing_cases: list[str] = []

    for case_id in EXPECTED_CASE_IDS:
        record = unique_records[case_id]
        failed_items: list[dict[str, Any]] = []
        pending_items: list[dict[str, Any]] = []
        if record is None:
            failed_items.append(
                {
                    "code": "record_unavailable",
                    "itemId": "record",
                    "message": "exactly one record is required for this case",
                }
            )
            ack_value = None
        else:
            if record.get("firstPassJsonParsed") is True:
                structure_counts["json"] += 1
            else:
                failed_items.append(
                    {
                        "code": "json_not_parsed",
                        "itemId": "firstPassJsonParsed",
                        "message": "first response was not strict parseable JSON",
                    }
                )

            if record.get("firstPassSchemaValid") is True:
                structure_counts["schema"] += 1
                first_schema_valid_count += 1
            else:
                failed_items.append(
                    {
                        "code": "schema_invalid",
                        "itemId": "firstPassSchemaValid",
                        "message": "first response did not pass the output schema",
                    }
                )

            if record.get("maskConversionValid") is True:
                structure_counts["mask"] += 1
            else:
                failed_items.append(
                    {
                        "code": "mask_conversion_failed",
                        "itemId": "maskConversionValid",
                        "message": "no final pattern converted to six masks",
                    }
                )

            if _final_valid(record):
                final_valid_count += 1
            elif record.get("repairAttempted") is True:
                repair_failure_cases.append(case_id)
                failed_items.append(
                    {
                        "code": "repair_failed",
                        "itemId": "repairValid",
                        "message": "one allowed repair still produced no valid result",
                    }
                )
            else:
                failed_items.append(
                    {
                        "code": "no_valid_final_pattern",
                        "itemId": "firstPassValid",
                        "message": "case has no valid first or repaired pattern",
                    }
                )

            latency = record.get("firstSchemaValidPatternLatencyMs")
            if _is_number(latency):
                latency_values.append(float(latency))
            else:
                latency_missing_cases.append(case_id)

            ack_value = _effective_ack(record, ack_by_run_id)
            if _ack_success(ack_value):
                structure_counts["ack"] += 1
            elif ack_value is None:
                if record.get("hardwareEligible") is True:
                    pending_items.append(
                        {
                            "code": "hardware_ack_not_recorded",
                            "itemId": "hardwareAck",
                            "message": "eligible pattern has no hardware ACK evidence",
                        }
                    )
            else:
                failed_items.append(
                    {
                        "code": "hardware_ack_failed",
                        "itemId": "hardwareAck",
                        "message": "hardware evidence did not contain a PATTERN ACK",
                    }
                )

            if ack_value is not None and record.get("hardwareEligible") is not True:
                invalid_dispatch_cases.append(case_id)
                failed_items.append(
                    {
                        "code": "invalid_pattern_hardware_dispatch",
                        "itemId": "hardwareAck",
                        "message": "hardware evidence exists for an ineligible pattern",
                    }
                )

        constraint_results: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        if record is not None:
            raw_results = record.get("constraintResults")
            if isinstance(raw_results, list):
                for result in raw_results:
                    if isinstance(result, Mapping) and isinstance(
                        result.get("constraintId"), str
                    ):
                        constraint_results[result["constraintId"]].append(result)
            else:
                data_issues.append(
                    {
                        "code": "constraint_results_type",
                        "message": f"caseId {case_id} constraintResults is not an array",
                    }
                )

        expected_constraint_ids = CASE_CONSTRAINT_IDS[case_id]
        for constraint_id in expected_constraint_ids:
            matches = constraint_results.get(constraint_id, [])
            passed = len(matches) == 1 and matches[0].get("passed") is True
            message = matches[0].get("message") if len(matches) == 1 else None
            instruction_items.append(
                {
                    "caseId": case_id,
                    "itemType": "constraint",
                    "itemId": constraint_id,
                    "passed": passed,
                }
            )
            if not passed:
                if not matches:
                    code = "constraint_missing"
                    failure_message = "pre-registered constraint result is missing"
                elif len(matches) > 1:
                    code = "constraint_duplicate"
                    failure_message = "pre-registered constraint result occurs more than once"
                else:
                    code = "constraint_failed"
                    failure_message = str(message or "constraint did not pass")
                failed_items.append(
                    {
                        "code": code,
                        "itemId": constraint_id,
                        "message": failure_message,
                    }
                )

        for result_id in sorted(set(constraint_results) - set(expected_constraint_ids)):
            data_issues.append(
                {
                    "code": "unexpected_constraint",
                    "message": f"caseId {case_id} has unexpected constraint {result_id}",
                }
            )

        if case_id in EDIT_CASE_IDS:
            edit_passed = record is not None and record.get("firstPassEditPolicyValid") is True
            instruction_items.append(
                {
                    "caseId": case_id,
                    "itemType": "editPolicy",
                    "itemId": "firstPassEditPolicyValid",
                    "passed": edit_passed,
                }
            )
            if not edit_passed:
                failed_items.append(
                    {
                        "code": "edit_policy_failed",
                        "itemId": "firstPassEditPolicyValid",
                        "message": "first response changed content outside the edit policy",
                    }
                )

        case_failures.append(
            {
                "caseId": case_id,
                "runId": record.get("runId") if record is not None else None,
                "failedItems": failed_items,
                "pendingItems": pending_items,
            }
        )

    structure_components = {
        "json": _component("firstPassJsonParsed", structure_counts["json"], 5),
        "schema": _component("firstPassSchemaValid", structure_counts["schema"], 10),
        "mask": _component("maskConversionValid", structure_counts["mask"], 5),
        "hardwareAck": _component("hardwareAck", structure_counts["ack"], 10),
    }
    structure_score = _round_score(
        sum(component["score"] for component in structure_components.values())
    )

    instruction_passed = sum(item["passed"] is True for item in instruction_items)
    instruction_score = _round_score(
        instruction_passed / EXPECTED_INSTRUCTION_ITEM_COUNT * 30
    )

    latency_median: float | None = None
    if len(latency_values) == len(EXPECTED_CASE_IDS):
        latency_median = float(statistics.median(latency_values))
    if repair_failure_cases:
        latency_score: int | None = 0
        latency_status = "forced_zero_invalid_after_repair"
    elif latency_median is None:
        latency_score = None
        latency_status = "unavailable_missing_six_samples"
    else:
        latency_score = _latency_score(latency_median)
        latency_status = "scored"

    automatic_score = (
        None
        if latency_score is None
        else _round_score(structure_score + instruction_score + latency_score)
    )
    case_set_complete = all(unique_records[case_id] is not None for case_id in EXPECTED_CASE_IDS)
    validity_gate_passed = (
        case_set_complete and first_schema_valid_count >= 5 and final_valid_count == 6
    )
    dispatch_gate_passed = not invalid_dispatch_cases

    return {
        "modelKey": f"{provider_id}:{requested_model}",
        "providerId": provider_id,
        "requestedModel": requested_model,
        "recordCount": len(records),
        "caseSetComplete": case_set_complete,
        "hardGates": {
            "schemaAndFinalValidity": {
                "passed": validity_gate_passed,
                "firstPassSchemaValidCount": first_schema_valid_count,
                "firstPassSchemaMinimum": 5,
                "finalValidCount": final_valid_count,
                "finalValidRequired": 6,
            },
            "noInvalidHardwareDispatch": {
                "passed": dispatch_gate_passed,
                "violationCaseIds": sorted(set(invalid_dispatch_cases)),
            },
            "passed": validity_gate_passed and dispatch_gate_passed,
        },
        "scores": {
            "structure": {
                "score": structure_score,
                "maxScore": 30,
                "components": structure_components,
            },
            "instruction": {
                "score": instruction_score,
                "maxScore": 30,
                "passedItems": instruction_passed,
                "totalItems": EXPECTED_INSTRUCTION_ITEM_COUNT,
                "constraintItemCount": EXPECTED_CONSTRAINT_COUNT,
                "editPolicyItemCount": len(EDIT_CASE_IDS),
                "items": instruction_items,
            },
            "blindListening": {
                "score": None,
                "maxScore": 30,
                "status": "pending_human_blind_listening",
            },
            "latency": {
                "score": latency_score,
                "maxScore": 10,
                "status": latency_status,
                "medianMs": latency_median,
                "sampleCount": len(latency_values),
                "missingCaseIds": latency_missing_cases,
                "forcedZeroCaseIds": sorted(set(repair_failure_cases)),
            },
            "automaticSubtotal": {
                "score": automatic_score,
                "maxScore": 70,
                "status": "scored" if automatic_score is not None else "incomplete",
            },
            "total": {
                "score": None,
                "maxScore": 100,
                "status": "pending_human_blind_listening",
            },
        },
        "caseFailures": case_failures,
        "dataQualityIssues": data_issues,
    }


def summarize_records(
    records: Iterable[Mapping[str, Any]],
    hardware_acks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize fixed-suite records without reading files or mutating inputs.

    Results are grouped by ``(providerId, requestedModel)``. The automatic
    instruction denominator is always the pre-registered 18 items, even when a
    result is missing. Blind-listening and the 100-point total intentionally
    remain ``None`` until a separate human review is completed.
    """

    ack_by_run_id, hardware_metadata, hardware_issues = _normalize_hardware_acks(
        hardware_acks
    )
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(f"record at index {index} is not a mapping")
        provider_id = str(record.get("providerId"))
        requested_model = str(record.get("requestedModel"))
        grouped[(provider_id, requested_model)].append(record)

    model_summaries = [
        _summarize_model(grouped[key], ack_by_run_id=ack_by_run_id)
        for key in sorted(grouped)
    ]
    known_run_ids = {
        record.get("runId")
        for model_records in grouped.values()
        for record in model_records
        if isinstance(record.get("runId"), str)
    }
    unmatched_ack_ids = sorted(set(ack_by_run_id) - known_run_ids)
    if unmatched_ack_ids:
        hardware_issues.append(
            {
                "code": "unmatched_hardware_ack",
                "message": "hardware ACK evidence has unmatched runIds: "
                + ", ".join(unmatched_ack_ids),
            }
        )

    audit_gaps: list[dict[str, str]] = []
    if hardware_metadata["provided"] is not True:
        audit_gaps.append(
            {
                "code": "hardware_ack_evidence_not_supplied",
                "message": "no external hardware ACK evidence was supplied",
            }
        )
    if hardware_metadata["deviceFirmwareCommitVerified"] is False:
        audit_gaps.append(
            {
                "code": "device_firmware_commit_unverified",
                "message": str(
                    hardware_metadata["deviceFirmwareCommitVerificationGap"]
                    or "device STATE did not verify the flashed firmware commit"
                ),
            }
        )

    return {
        "scoringVersion": SCORING_VERSION,
        "expectedCaseCountPerModel": len(EXPECTED_CASE_IDS),
        "expectedInstructionItemCount": EXPECTED_INSTRUCTION_ITEM_COUNT,
        "assumptions": [
            "JSON and schema use first-pass fields; mask uses the final maskConversionValid field, as pre-registered.",
            "Instruction scoring uses first-pass constraintResults and firstPassEditPolicyValid; repair evidence never overwrites first-pass deductions.",
            "Hardware evidence is joined only by exact runId; a missing ACK remains unverified and earns zero ACK points.",
            "Any attempted repair whose repairValid is not true forces that model's latency score to zero.",
            "A PATTERN ACK proves protocol acceptance only; it does not verify the flashed firmware commit.",
        ],
        "hardwareEvidence": hardware_metadata,
        "auditGaps": audit_gaps,
        "dataQualityIssues": hardware_issues,
        "models": model_summaries,
    }
