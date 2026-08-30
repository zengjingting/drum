from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import DEFAULT_RESULTS_ROOT, EXPERIMENT_VERSION


RUN_MODES = frozenset({"smoke", "warmup", "formal"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def empty_human_rating() -> dict[str, Any]:
    return {
        "blindOrder": None,
        "styleRecognition": None,
        "grooveNaturalness": None,
        "willingnessToUse": None,
    }


def make_base_record(
    *,
    run_id: str,
    run_mode: str,
    session_id: str,
    case_id: str,
    provider_id: str,
    requested_model: str,
    deployment: str,
    schema_mode: str,
    thinking_mode: str,
    temperature: float,
    top_p: float,
    max_output_tokens: int,
    firmware_commit: str | None,
    web_commit: str | None,
    asset_manifest_sha256: str | None,
) -> dict[str, Any]:
    if run_mode not in RUN_MODES:
        raise ValueError(f"unsupported run mode: {run_mode}")
    return {
        "experimentVersion": EXPERIMENT_VERSION,
        "runMode": run_mode,
        "sessionId": session_id,
        "runId": run_id,
        "caseId": case_id,
        "providerId": provider_id,
        "requestedModel": requested_model,
        "responseReportedModel": None,
        "documentedModelVersion": None,
        "modelVersionEvidence": None,
        "deployment": deployment,
        "schemaMode": schema_mode,
        "thinkingMode": thinking_mode,
        "temperature": temperature,
        "topP": top_p,
        "maxOutputTokens": max_output_tokens,
        "unsupportedParameters": [],
        "startedAt": utc_now_iso(),
        "status": "pending",
        "skipReason": None,
        "providerError": None,
        "firstTokenLatencyMs": None,
        "completeResponseLatencyMs": None,
        "firstSchemaValidPatternLatencyMs": None,
        "firstValidPatternLatencyMs": None,
        "rawOutput": None,
        "parsedPattern": None,
        "firstPassJsonParsed": False,
        "firstPassSchemaValid": False,
        "firstPassConstraintsValid": False,
        "firstPassEditPolicyValid": False,
        "firstPassValid": False,
        "validationErrors": [],
        "constraintResults": [],
        "repairAttempted": False,
        "repairRawOutput": None,
        "repairFirstTokenLatencyMs": None,
        "repairCompleteResponseLatencyMs": None,
        "repairSchemaValid": None,
        "repairConstraintsValid": None,
        "repairEditPolicyValid": None,
        "repairValid": None,
        "repairValidationErrors": [],
        "repairConstraintResults": [],
        "firstPassPatternMasks": None,
        "firstPassMaskConversionValid": False,
        "patternMasks": None,
        "maskConversionValid": False,
        "hardwareEligible": False,
        "hardwareAck": None,
        "humanRating": empty_human_rating(),
        "firmwareCommit": firmware_commit,
        "webCommit": web_commit,
        "assetManifestSha256": asset_manifest_sha256,
        "finishedAt": None,
    }


@dataclass
class JsonlRunStore:
    session_id: str
    mode: str
    root: Path = DEFAULT_RESULTS_ROOT

    def __post_init__(self) -> None:
        if self.mode not in RUN_MODES:
            raise ValueError(f"unsupported run mode: {self.mode}")
        if not self.session_id or any(char in self.session_id for char in "/\\"):
            raise ValueError("session_id must be a non-empty filename-safe value")

    @property
    def path(self) -> Path:
        return self.root / self.mode / f"{self.session_id}.jsonl"

    def append(self, record: dict[str, Any]) -> Path:
        record_mode = record.get("runMode")
        if record_mode != self.mode:
            raise ValueError(
                f"record mode {record_mode!r} cannot be written to {self.mode!r} store"
            )
        if record.get("sessionId") != self.session_id:
            raise ValueError("record sessionId does not match store session_id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
        return self.path
