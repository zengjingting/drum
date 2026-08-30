from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .cases import build_request
from .constants import PATTERN_SCHEMA_PATH
from .masks import MaskConversionError, pattern_to_masks
from .prompts import build_initial_messages, build_repair_messages
from .providers import GenerationSettings, ProviderAdapter, ProviderError
from .records import make_base_record, utc_now_iso
from .validation import parse_pattern_json, validate_case_output


def load_output_schema(path: Path = PATTERN_SCHEMA_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _apply_validation(
    case: dict[str, Any], raw_output: str
) -> tuple[dict[str, Any] | None, Any, list[dict[str, str]]]:
    pattern, parse_issues = parse_pattern_json(raw_output)
    if parse_issues:
        return None, None, [issue.to_dict() for issue in parse_issues]
    validation = validate_case_output(case, pattern)
    return pattern, validation, validation.errors_as_dicts()


def _record_first_validation(
    record: dict[str, Any], pattern: dict[str, Any] | None, validation: Any, errors: list[dict[str, str]]
) -> None:
    record["firstPassJsonParsed"] = pattern is not None
    record["validationErrors"] = errors
    if validation is None:
        return
    record["firstPassSchemaValid"] = validation.schema_valid
    record["firstPassConstraintsValid"] = validation.constraints_valid
    record["firstPassEditPolicyValid"] = validation.edit_policy_valid
    record["firstPassValid"] = validation.valid
    record["constraintResults"] = [item.to_dict() for item in validation.constraint_results]


def _record_repair_validation(
    record: dict[str, Any], pattern: dict[str, Any] | None, validation: Any, errors: list[dict[str, str]]
) -> None:
    record["repairValidationErrors"] = errors
    if validation is None:
        record["repairSchemaValid"] = False
        record["repairConstraintsValid"] = False
        record["repairEditPolicyValid"] = False
        record["repairValid"] = False
        return
    record["repairSchemaValid"] = validation.schema_valid
    record["repairConstraintsValid"] = validation.constraints_valid
    record["repairEditPolicyValid"] = validation.edit_policy_valid
    record["repairValid"] = validation.valid
    record["repairConstraintResults"] = [item.to_dict() for item in validation.constraint_results]


def _convert_masks(pattern: dict[str, Any] | None, validation: Any) -> tuple[dict[str, int] | None, str | None]:
    if pattern is None or validation is None or not validation.schema_valid:
        return None, None
    try:
        return pattern_to_masks(pattern), None
    except MaskConversionError as exc:
        return None, str(exc)


def run_case(
    *,
    case: dict[str, Any],
    adapter: ProviderAdapter,
    run_mode: str,
    session_id: str,
    settings: GenerationSettings,
    allow_repair: bool,
    firmware_commit: str | None = None,
    web_commit: str | None = None,
    asset_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    run_id = f"{session_id}-{adapter.provider_id}-{case['caseId']}"
    record = make_base_record(
        run_id=run_id,
        run_mode=run_mode,
        session_id=session_id,
        case_id=case["caseId"],
        provider_id=adapter.provider_id,
        requested_model=adapter.requested_model,
        deployment=adapter.deployment,
        schema_mode=adapter.schema_mode,
        thinking_mode=adapter.thinking_mode,
        temperature=settings.temperature,
        top_p=settings.top_p,
        max_output_tokens=settings.max_output_tokens,
        firmware_commit=firmware_commit,
        web_commit=web_commit,
        asset_manifest_sha256=asset_manifest_sha256,
    )
    record["unsupportedParameters"] = list(adapter.unsupported_parameters)
    record["documentedModelVersion"] = adapter.documented_model_version

    availability = adapter.availability()
    if not availability.available:
        record["status"] = "skipped"
        record["skipReason"] = availability.reason
        record["finishedAt"] = utc_now_iso()
        return record

    request = build_request(case)
    schema = load_output_schema()
    initial_messages = build_initial_messages(request, schema)
    wall_started = time.perf_counter()
    try:
        response = adapter.generate(
            messages=initial_messages,
            output_schema=schema,
            settings=settings,
        )
    except ProviderError as exc:
        record["status"] = "error"
        record["providerError"] = str(exc)
        record["finishedAt"] = utc_now_iso()
        return record

    record["responseReportedModel"] = response.response_reported_model
    if response.response_reported_model is None:
        record["modelVersionEvidence"] = "not_reported_by_provider"
    elif response.response_reported_model == adapter.requested_model:
        record["modelVersionEvidence"] = "response_reports_requested_model"
    elif (
        adapter.documented_model_version is not None
        and response.response_reported_model == adapter.documented_model_version
    ):
        record["modelVersionEvidence"] = "response_reports_documented_version"
    else:
        record["modelVersionEvidence"] = "response_reports_other_model"
    record["firstTokenLatencyMs"] = response.first_token_latency_ms
    record["completeResponseLatencyMs"] = response.complete_response_latency_ms
    record["rawOutput"] = response.raw_output
    record["providerResponseMetadata"] = response.response_metadata

    pattern, validation, errors = _apply_validation(case, response.raw_output)
    _record_first_validation(record, pattern, validation, errors)
    first_masks, first_mask_error = _convert_masks(pattern, validation)
    if first_masks is not None:
        record["firstPassPatternMasks"] = first_masks
        record["firstPassMaskConversionValid"] = True
        record["patternMasks"] = first_masks
        record["maskConversionValid"] = True
    elif first_mask_error is not None:
        record["validationErrors"].append(
            {
                "code": "mask_conversion",
                "path": "$.tracks",
                "message": first_mask_error,
                "category": "mask",
            }
        )
    if validation is not None and validation.schema_valid:
        record["firstSchemaValidPatternLatencyMs"] = round((time.perf_counter() - wall_started) * 1000)

    final_pattern = pattern
    final_validation = validation
    if validation is None or not validation.valid:
        if allow_repair:
            record["repairAttempted"] = True
            repair_messages = build_repair_messages(
                request,
                schema,
                response.raw_output,
                errors,
            )
            try:
                repair_response = adapter.generate(
                    messages=repair_messages,
                    output_schema=schema,
                    settings=settings,
                )
            except ProviderError as exc:
                record["providerError"] = f"repair failed: {exc}"
                record["repairValid"] = False
            else:
                record["repairRawOutput"] = repair_response.raw_output
                record["repairFirstTokenLatencyMs"] = repair_response.first_token_latency_ms
                record["repairCompleteResponseLatencyMs"] = repair_response.complete_response_latency_ms
                repair_pattern, repair_validation, repair_errors = _apply_validation(
                    case, repair_response.raw_output
                )
                _record_repair_validation(
                    record, repair_pattern, repair_validation, repair_errors
                )
                final_pattern = repair_pattern
                final_validation = repair_validation
                repair_masks, repair_mask_error = _convert_masks(
                    repair_pattern, repair_validation
                )
                if repair_masks is not None:
                    record["patternMasks"] = repair_masks
                    record["maskConversionValid"] = True
                elif repair_mask_error is not None:
                    record["repairValidationErrors"].append(
                        {
                            "code": "mask_conversion",
                            "path": "$.tracks",
                            "message": repair_mask_error,
                            "category": "mask",
                        }
                    )

    if final_pattern is not None:
        record["parsedPattern"] = final_pattern
    if final_validation is not None and final_validation.valid:
        record["firstValidPatternLatencyMs"] = round((time.perf_counter() - wall_started) * 1000)
        record["hardwareEligible"] = record["maskConversionValid"]

    record["status"] = "completed"
    record["finishedAt"] = utc_now_iso()
    return record
