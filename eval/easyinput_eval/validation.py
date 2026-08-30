from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from .constants import (
    BEAT_STEPS,
    DEFAULT_BPM,
    MAX_BPM,
    MIN_BPM,
    PATTERN_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    STEPS_PER_BAR,
    SUPPORTED_CONSTRAINT_TYPES,
    TRACK_IDS,
    TRACK_ID_SET,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str
    category: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "category": self.category,
        }


@dataclass(frozen=True)
class ConstraintResult:
    constraint_id: str
    constraint_type: str
    passed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraintId": self.constraint_id,
            "constraintType": self.constraint_type,
            "passed": self.passed,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    schema_valid: bool
    constraints_valid: bool = True
    edit_policy_valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    constraint_results: list[ConstraintResult] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.schema_valid and self.constraints_valid and self.edit_policy_valid

    def errors_as_dicts(self) -> list[dict[str, str]]:
        return [issue.to_dict() for issue in self.issues]


def _issue(code: str, path: str, message: str, category: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, message=message, category=category)


def parse_pattern_json(raw_output: str) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    try:
        parsed = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [
            _issue("json_parse", "$", f"output is not strict JSON: {exc}", "schema")
        ]
    if not isinstance(parsed, dict):
        return None, [
            _issue("root_type", "$", "pattern root must be an object", "schema")
        ]
    return parsed, []


def validate_pattern(pattern: Any, require_nonempty: bool = True) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if not isinstance(pattern, dict):
        return ValidationResult(
            schema_valid=False,
            issues=[_issue("root_type", "$", "pattern must be an object", "schema")],
        )

    required = {"schemaVersion", "name", "style", "bpm", "tracks"}
    allowed = required | {"designNote"}
    keys = set(pattern)
    for missing in sorted(required - keys):
        issues.append(_issue("required", f"$.{missing}", "required field is missing", "schema"))
    for extra in sorted(keys - allowed):
        issues.append(
            _issue("additional_property", f"$.{extra}", "field is not allowed", "schema")
        )

    if pattern.get("schemaVersion") != PATTERN_SCHEMA_VERSION:
        issues.append(
            _issue(
                "schema_version",
                "$.schemaVersion",
                f"must equal {PATTERN_SCHEMA_VERSION!r}",
                "schema",
            )
        )

    for field_name, maximum in (("name", 80), ("style", 40)):
        value = pattern.get(field_name)
        if not isinstance(value, str) or not value or len(value) > maximum:
            issues.append(
                _issue(
                    "string_range",
                    f"$.{field_name}",
                    f"must be a non-empty string of at most {maximum} characters",
                    "schema",
                )
            )

    bpm = pattern.get("bpm")
    if type(bpm) is not int or not MIN_BPM <= bpm <= MAX_BPM:
        issues.append(
            _issue(
                "bpm_range",
                "$.bpm",
                f"must be an integer from {MIN_BPM} to {MAX_BPM}",
                "schema",
            )
        )

    design_note = pattern.get("designNote")
    if design_note is not None and (
        not isinstance(design_note, str) or len(design_note) > 300
    ):
        issues.append(
            _issue(
                "design_note",
                "$.designNote",
                "must be a string of at most 300 characters",
                "schema",
            )
        )

    tracks = pattern.get("tracks")
    if not isinstance(tracks, dict):
        issues.append(_issue("tracks_type", "$.tracks", "must be an object", "schema"))
    else:
        track_keys = set(tracks)
        for missing in sorted(TRACK_ID_SET - track_keys):
            issues.append(
                _issue("required_track", f"$.tracks.{missing}", "track is missing", "schema")
            )
        for extra in sorted(track_keys - TRACK_ID_SET):
            issues.append(
                _issue("unknown_track", f"$.tracks.{extra}", "track is not allowed", "schema")
            )
        for track_id in TRACK_IDS:
            if track_id not in tracks:
                continue
            track = tracks[track_id]
            if not isinstance(track, list) or len(track) != STEPS_PER_BAR:
                issues.append(
                    _issue(
                        "track_length",
                        f"$.tracks.{track_id}",
                        "must be an array with exactly 16 steps",
                        "schema",
                    )
                )
                continue
            for index, value in enumerate(track):
                if type(value) is not int or value not in (0, 1):
                    issues.append(
                        _issue(
                            "step_value",
                            f"$.tracks.{track_id}[{index}]",
                            "must be integer 0 or 1",
                            "schema",
                        )
                    )

        has_trigger = any(
            type(value) is int and value == 1
            for track_id in TRACK_IDS
            if isinstance(tracks.get(track_id), list)
            for value in tracks[track_id]
        )
        if require_nonempty and not has_trigger:
            issues.append(
                _issue(
                    "empty_pattern",
                    "$.tracks",
                    "at least one trigger is required",
                    "schema",
                )
            )

    return ValidationResult(schema_valid=not issues, issues=issues)


def _validate_fixed_request_fields(request: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    expected_grid = {
        "beatsPerBar": 4,
        "stepsPerBeat": 4,
        "stepsPerBar": 16,
        "humanStepNumbering": "1-16",
        "beatSteps": list(BEAT_STEPS),
    }
    expected_tempo = {"minBpm": MIN_BPM, "maxBpm": MAX_BPM, "defaultBpm": DEFAULT_BPM}
    if request.get("grid") != expected_grid:
        issues.append(_issue("grid_contract", "$.grid", "grid contract does not match v1", "schema"))
    if request.get("tempo") != expected_tempo:
        issues.append(
            _issue("tempo_contract", "$.tempo", "tempo contract does not match v1", "schema")
        )

    instruments = request.get("instruments")
    if not isinstance(instruments, list) or len(instruments) != 6:
        issues.append(
            _issue("instrument_count", "$.instruments", "must list exactly six instruments", "schema")
        )
    else:
        ids = [item.get("trackId") for item in instruments if isinstance(item, dict)]
        if len(ids) != 6 or set(ids) != TRACK_ID_SET or len(set(ids)) != 6:
            issues.append(
                _issue(
                    "instrument_ids",
                    "$.instruments",
                    "must contain each allowed trackId exactly once",
                    "schema",
                )
            )
        for index, instrument in enumerate(instruments):
            if not isinstance(instrument, dict) or set(instrument) != {"trackId", "name", "role"}:
                issues.append(
                    _issue(
                        "instrument_shape",
                        f"$.instruments[{index}]",
                        "must contain exactly trackId, name, and role",
                        "schema",
                    )
                )
            elif not all(
                isinstance(instrument[field], str) and instrument[field]
                for field in ("trackId", "name", "role")
            ):
                issues.append(
                    _issue(
                        "instrument_string",
                        f"$.instruments[{index}]",
                        "instrument fields must be non-empty strings",
                        "schema",
                    )
                )

    expected_unsupported = [
        "velocity",
        "swing",
        "triplet",
        "microtiming",
        "instrumentsOutsideTheList",
    ]
    if request.get("unsupportedFeatures") != expected_unsupported:
        issues.append(
            _issue(
                "unsupported_contract",
                "$.unsupportedFeatures",
                "unsupported feature list does not match v1",
                "schema",
            )
        )
    return issues


def _validate_field_path(path: Any) -> bool:
    if path in {"name", "style", "bpm"}:
        return True
    if not isinstance(path, str) or not path.startswith("tracks."):
        return False
    return path.split(".", 1)[1] in TRACK_ID_SET


def _validate_edit_policy(policy: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(policy, dict):
        return [_issue("edit_policy_type", "$.editPolicy", "must be an object", "schema")]
    allowed = {"mutableFields", "immutableFields", "mutableCells"}
    required = {"mutableFields", "immutableFields"}
    if set(policy) - allowed:
        issues.append(
            _issue("edit_policy_extra", "$.editPolicy", "contains unknown fields", "schema")
        )
    if not required <= set(policy):
        issues.append(
            _issue("edit_policy_required", "$.editPolicy", "missing required fields", "schema")
        )
        return issues

    mutable = policy.get("mutableFields")
    immutable = policy.get("immutableFields")
    for key, value in (("mutableFields", mutable), ("immutableFields", immutable)):
        if not isinstance(value, list) or len(value) != len(set(value)) or not all(
            _validate_field_path(path) for path in value
        ):
            issues.append(
                _issue(
                    "edit_field_paths",
                    f"$.editPolicy.{key}",
                    "must be a unique list of supported field paths",
                    "schema",
                )
            )
    if isinstance(mutable, list) and isinstance(immutable, list) and set(mutable) & set(immutable):
        issues.append(
            _issue(
                "edit_policy_overlap",
                "$.editPolicy",
                "mutableFields and immutableFields must not overlap",
                "schema",
            )
        )

    mutable_cells = policy.get("mutableCells")
    if mutable_cells is not None:
        if not isinstance(mutable_cells, list):
            issues.append(
                _issue("mutable_cells_type", "$.editPolicy.mutableCells", "must be an array", "schema")
            )
        else:
            seen_tracks: set[str] = set()
            for index, item in enumerate(mutable_cells):
                path = f"$.editPolicy.mutableCells[{index}]"
                if not isinstance(item, dict) or set(item) != {"track", "steps"}:
                    issues.append(_issue("mutable_cell_shape", path, "must contain track and steps", "schema"))
                    continue
                track = item["track"]
                steps = item["steps"]
                if track not in TRACK_ID_SET or track in seen_tracks:
                    issues.append(
                        _issue(
                            "mutable_cell_track",
                            f"{path}.track",
                            "track must be allowed and occur once",
                            "schema",
                        )
                    )
                seen_tracks.add(track)
                if f"tracks.{track}" not in set(mutable or []):
                    issues.append(
                        _issue(
                            "mutable_cell_not_mutable",
                            path,
                            "mutableCells track must also appear in mutableFields",
                            "schema",
                        )
                    )
                if (
                    not isinstance(steps, list)
                    or not steps
                    or len(steps) != len(set(steps))
                    or any(type(step) is not int or not 1 <= step <= 16 for step in steps)
                ):
                    issues.append(
                        _issue(
                            "mutable_cell_steps",
                            f"{path}.steps",
                            "steps must be unique integers from 1 to 16",
                            "schema",
                        )
                    )
    return issues


def validate_request(request: Any) -> ValidationResult:
    if not isinstance(request, dict):
        return ValidationResult(
            schema_valid=False,
            issues=[_issue("root_type", "$", "request must be an object", "schema")],
        )
    issues: list[ValidationIssue] = []
    required = {
        "schemaVersion",
        "task",
        "userPrompt",
        "grid",
        "tempo",
        "instruments",
        "unsupportedFeatures",
        "currentPattern",
    }
    allowed = required | {"editPolicy"}
    for missing in sorted(required - set(request)):
        issues.append(_issue("required", f"$.{missing}", "required field is missing", "schema"))
    for extra in sorted(set(request) - allowed):
        issues.append(_issue("additional_property", f"$.{extra}", "field is not allowed", "schema"))

    if request.get("schemaVersion") != REQUEST_SCHEMA_VERSION:
        issues.append(
            _issue(
                "schema_version",
                "$.schemaVersion",
                f"must equal {REQUEST_SCHEMA_VERSION!r}",
                "schema",
            )
        )
    task = request.get("task")
    if task not in {"generate", "edit"}:
        issues.append(_issue("task", "$.task", "must be generate or edit", "schema"))
    prompt = request.get("userPrompt")
    if not isinstance(prompt, str) or not prompt or len(prompt) > 500:
        issues.append(
            _issue("user_prompt", "$.userPrompt", "must be a non-empty string up to 500 characters", "schema")
        )
    issues.extend(_validate_fixed_request_fields(request))

    current = request.get("currentPattern")
    if task == "generate":
        if current is not None:
            issues.append(
                _issue("generate_current", "$.currentPattern", "must be null for generate", "schema")
            )
        if "editPolicy" in request:
            issues.append(_issue("generate_policy", "$.editPolicy", "not allowed for generate", "schema"))
    elif task == "edit":
        current_result = validate_pattern(current)
        issues.extend(
            _issue(issue.code, f"$.currentPattern{issue.path[1:]}", issue.message, "schema")
            for issue in current_result.issues
        )
        issues.extend(_validate_edit_policy(request.get("editPolicy")))

    return ValidationResult(schema_valid=not issues, issues=issues)


def _active_steps(track: list[int]) -> list[int]:
    return [index + 1 for index, value in enumerate(track) if value == 1]


def _constraint_result(
    constraint: dict[str, Any], passed: bool, message: str
) -> ConstraintResult:
    return ConstraintResult(
        constraint_id=str(constraint.get("id", "missing-id")),
        constraint_type=str(constraint.get("type", "missing-type")),
        passed=passed,
        message=message,
    )


def evaluate_constraints(
    case: dict[str, Any], pattern: dict[str, Any]
) -> tuple[list[ConstraintResult], list[ValidationIssue]]:
    results: list[ConstraintResult] = []
    issues: list[ValidationIssue] = []
    tracks = pattern["tracks"]
    current = case.get("currentPattern")

    for constraint in case.get("constraints", []):
        constraint_type = constraint.get("type")
        constraint_id = constraint.get("id", "missing-id")
        if constraint_type not in SUPPORTED_CONSTRAINT_TYPES:
            result = _constraint_result(constraint, False, "unsupported constraint type")
        elif constraint_type == "bpm_equals":
            expected = constraint["value"]
            actual = pattern["bpm"]
            result = _constraint_result(
                constraint, actual == expected, f"expected bpm {expected}, got {actual}"
            )
        elif constraint_type == "track_exact_steps":
            actual = _active_steps(tracks[constraint["track"]])
            expected = constraint["steps"]
            result = _constraint_result(
                constraint, actual == expected, f"expected active steps {expected}, got {actual}"
            )
        elif constraint_type == "track_steps_on":
            track = tracks[constraint["track"]]
            missing = [step for step in constraint["steps"] if track[step - 1] != 1]
            result = _constraint_result(
                constraint, not missing, f"steps that were not on: {missing}"
            )
        elif constraint_type == "track_steps_value":
            track = tracks[constraint["track"]]
            expected = constraint["value"]
            wrong = [step for step in constraint["steps"] if track[step - 1] != expected]
            result = _constraint_result(
                constraint, not wrong, f"steps not equal to {expected}: {wrong}"
            )
        elif constraint_type == "track_count_range":
            count = sum(tracks[constraint["track"]])
            passed = constraint["min"] <= count <= constraint["max"]
            result = _constraint_result(
                constraint,
                passed,
                f"trigger count {count}, expected {constraint['min']}..{constraint['max']}",
            )
        elif constraint_type == "track_has_trigger_outside":
            active = set(_active_steps(tracks[constraint["track"]]))
            excluded = set(constraint["steps"])
            outside = sorted(active - excluded)
            result = _constraint_result(
                constraint, bool(outside), f"active steps outside {sorted(excluded)}: {outside}"
            )
        elif constraint_type == "track_count_less_than_current":
            track_id = constraint["track"]
            actual = sum(tracks[track_id])
            before = sum(current["tracks"][track_id])
            result = _constraint_result(
                constraint, actual < before, f"trigger count changed from {before} to {actual}"
            )
        elif constraint_type == "tracks_count_range_in_steps":
            count = sum(
                tracks[track_id][step - 1]
                for track_id in constraint["tracks"]
                for step in constraint["steps"]
            )
            passed = constraint["min"] <= count <= constraint["max"]
            result = _constraint_result(
                constraint,
                passed,
                f"trigger count in selected cells {count}, expected {constraint['min']}..{constraint['max']}",
            )
        else:  # track_count_range_in_steps
            count = sum(
                tracks[constraint["track"]][step - 1] for step in constraint["steps"]
            )
            passed = constraint["min"] <= count <= constraint["max"]
            result = _constraint_result(
                constraint,
                passed,
                f"trigger count in selected steps {count}, expected {constraint['min']}..{constraint['max']}",
            )

        results.append(result)
        if not result.passed:
            issues.append(
                _issue(
                    "constraint_failed",
                    f"$case.constraints.{constraint_id}",
                    result.message,
                    "constraint",
                )
            )
    return results, issues


def evaluate_edit_policy(
    case: dict[str, Any], pattern: dict[str, Any]
) -> list[ValidationIssue]:
    if case.get("task") != "edit":
        return []
    current = case["currentPattern"]
    policy = case["editPolicy"]
    issues: list[ValidationIssue] = []

    for path in policy["immutableFields"]:
        if path.startswith("tracks."):
            track_id = path.split(".", 1)[1]
            before = current["tracks"][track_id]
            after = pattern["tracks"][track_id]
        else:
            before = current[path]
            after = pattern[path]
        if after != before:
            issues.append(
                _issue(
                    "immutable_field_changed",
                    f"$.{path}",
                    "field differs from currentPattern",
                    "edit_policy",
                )
            )

    cell_rules = {item["track"]: set(item["steps"]) for item in policy.get("mutableCells", [])}
    for field_path in policy["mutableFields"]:
        if not field_path.startswith("tracks."):
            continue
        track_id = field_path.split(".", 1)[1]
        if track_id not in cell_rules:
            continue
        allowed_steps = cell_rules[track_id]
        before = current["tracks"][track_id]
        after = pattern["tracks"][track_id]
        for index, (before_value, after_value) in enumerate(zip(before, after), start=1):
            if index not in allowed_steps and before_value != after_value:
                issues.append(
                    _issue(
                        "immutable_cell_changed",
                        f"$.tracks.{track_id}[{index - 1}]",
                        f"step {index} is outside mutableCells",
                        "edit_policy",
                    )
                )
    return issues


def validate_case_output(case: dict[str, Any], pattern: Any) -> ValidationResult:
    schema_result = validate_pattern(pattern)
    if not schema_result.schema_valid:
        return schema_result

    constraint_results, constraint_issues = evaluate_constraints(case, pattern)
    edit_issues = evaluate_edit_policy(case, pattern)
    return ValidationResult(
        schema_valid=True,
        constraints_valid=not constraint_issues,
        edit_policy_valid=not edit_issues,
        issues=constraint_issues + edit_issues,
        constraint_results=constraint_results,
    )


def validate_benchmark_case_definition(case: Any) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if not isinstance(case, dict):
        return ValidationResult(
            schema_valid=False,
            issues=[_issue("case_type", "$case", "case must be an object", "benchmark")],
        )
    for key in ("caseId", "task", "userPrompt", "currentPattern", "constraints"):
        if key not in case:
            issues.append(_issue("case_required", f"$case.{key}", "field is missing", "benchmark"))
    constraints = case.get("constraints")
    if not isinstance(constraints, list):
        issues.append(
            _issue("constraints_type", "$case.constraints", "must be an array", "benchmark")
        )
    else:
        ids: list[Any] = []
        for index, constraint in enumerate(constraints):
            if not isinstance(constraint, dict):
                issues.append(
                    _issue(
                        "constraint_shape",
                        f"$case.constraints[{index}]",
                        "must be an object",
                        "benchmark",
                    )
                )
                continue
            ids.append(constraint.get("id"))
            if constraint.get("type") not in SUPPORTED_CONSTRAINT_TYPES:
                issues.append(
                    _issue(
                        "constraint_type",
                        f"$case.constraints[{index}].type",
                        "unsupported constraint type",
                        "benchmark",
                    )
                )
        if len(ids) != len(set(ids)) or any(not value for value in ids):
            issues.append(
                _issue(
                    "constraint_ids",
                    "$case.constraints",
                    "constraint IDs must be present and unique within a case",
                    "benchmark",
                )
            )
    return ValidationResult(schema_valid=not issues, issues=issues)
