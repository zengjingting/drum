import copy
import json
from pathlib import Path
from typing import Any

from .constants import BENCHMARK_CASES_PATH, EXPERIMENT_VERSION


class BenchmarkDataError(ValueError):
    """Raised when the pre-registered benchmark data is internally invalid."""


def load_benchmark_document(path: Path = BENCHMARK_CASES_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if document.get("experimentVersion") != EXPERIMENT_VERSION:
        raise BenchmarkDataError(
            f"unexpected experimentVersion: {document.get('experimentVersion')!r}"
        )
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise BenchmarkDataError("benchmark must contain exactly six cases")
    case_ids = [case.get("caseId") for case in cases if isinstance(case, dict)]
    if len(case_ids) != 6 or len(set(case_ids)) != 6:
        raise BenchmarkDataError("all six benchmark caseId values must be unique")
    return document


def load_benchmark_cases(path: Path = BENCHMARK_CASES_PATH) -> list[dict[str, Any]]:
    return load_benchmark_document(path)["cases"]


def get_case(case_id: str, path: Path = BENCHMARK_CASES_PATH) -> dict[str, Any]:
    for case in load_benchmark_cases(path):
        if case["caseId"] == case_id:
            return case
    raise KeyError(f"unknown benchmark case: {case_id}")


def build_request(
    case: dict[str, Any], path: Path = BENCHMARK_CASES_PATH
) -> dict[str, Any]:
    document = load_benchmark_document(path)
    request = copy.deepcopy(document["requestDefaults"])
    request.update(
        {
            "task": case["task"],
            "userPrompt": case["userPrompt"],
            "currentPattern": copy.deepcopy(case.get("currentPattern")),
        }
    )
    if case["task"] == "edit":
        request["editPolicy"] = copy.deepcopy(case["editPolicy"])
    return request
