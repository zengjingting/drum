from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import build_request, get_case, load_benchmark_cases
from .constants import (
    DEFAULT_RESULTS_ROOT,
    PATTERN_SCHEMA_PATH,
    REQUEST_SCHEMA_PATH,
)
from .providers import GenerationSettings, ProviderAdapter, default_adapters
from .records import JsonlRunStore
from .runner import run_case
from .validation import validate_benchmark_case_definition, validate_request


FORMAL_CONFIRMATION = "RUN_18_CASES_WITH_UP_TO_ONE_REPAIR_EACH"


def _session_id(mode: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{mode}-{uuid.uuid4().hex[:8]}"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def inspect_contract() -> int:
    failures: list[str] = []
    for schema_path in (PATTERN_SCHEMA_PATH, REQUEST_SCHEMA_PATH):
        try:
            schema = _load_json(schema_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(f"{schema_path}: {exc}")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            failures.append(f"{schema_path}: expected JSON Schema draft 2020-12")

    cases = load_benchmark_cases()
    for case in cases:
        definition = validate_benchmark_case_definition(case)
        request = validate_request(build_request(case))
        for issue in definition.issues + request.issues:
            failures.append(f"{case.get('caseId')}: {issue.path}: {issue.message}")

    report = {
        "ok": not failures,
        "caseCount": len(cases),
        "caseIds": [case["caseId"] for case in cases],
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def _settings(args: argparse.Namespace) -> GenerationSettings:
    return GenerationSettings(
        temperature=args.temperature,
        top_p=args.top_p,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )


def _print_record_summary(record: dict[str, Any], path: Path) -> None:
    summary = {
        "runId": record["runId"],
        "runMode": record["runMode"],
        "status": record["status"],
        "schemaValid": record["firstPassSchemaValid"],
        "constraintsValid": record["firstPassConstraintsValid"],
        "editPolicyValid": record["firstPassEditPolicyValid"],
        "repairValid": record["repairValid"],
        "resultsFile": str(path),
        "skipReason": record["skipReason"],
        "providerError": record["providerError"],
    }
    print(json.dumps(summary, ensure_ascii=False))


def run_smoke(args: argparse.Namespace) -> int:
    adapters = default_adapters()
    selected_ids = args.provider or ["ollama"]
    unknown = sorted(set(selected_ids) - set(adapters))
    if unknown:
        print(f"unknown providers: {unknown}", file=sys.stderr)
        return 2
    session_id = args.session_id or _session_id("smoke")
    store = JsonlRunStore(session_id=session_id, mode="smoke", root=args.results_root)
    case = get_case(args.case)
    exit_code = 0
    for provider_id in selected_ids:
        record = run_case(
            case=case,
            adapter=adapters[provider_id],
            run_mode="smoke",
            session_id=session_id,
            settings=_settings(args),
            allow_repair=args.allow_repair,
        )
        path = store.append(record)
        _print_record_summary(record, path)
        if record["status"] == "error":
            exit_code = 1
    return exit_code


def _preflight_formal(adapters: dict[str, ProviderAdapter]) -> list[str]:
    failures: list[str] = []
    for provider_id in ("ollama", "zhipu", "deepseek"):
        availability = adapters[provider_id].availability()
        if not availability.available:
            failures.append(f"{provider_id}: {availability.reason}")
    return failures


def run_formal(args: argparse.Namespace) -> int:
    if args.confirm_formal != FORMAL_CONFIRMATION:
        print(
            "formal run blocked: pass "
            f"--confirm-formal {FORMAL_CONFIRMATION} after freezing the experiment",
            file=sys.stderr,
        )
        return 2
    adapters = default_adapters()
    failures = _preflight_formal(adapters)
    if failures:
        print("formal run blocked; every provider must be available:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 2

    session_id = args.session_id or _session_id("formal")
    settings = _settings(args)
    cases = load_benchmark_cases()

    warmup_session = f"{session_id}-warmup"
    warmup_store = JsonlRunStore(
        session_id=warmup_session,
        mode="warmup",
        root=args.results_root,
    )
    warmup_case = get_case("G-HOUSE")
    for adapter in adapters.values():
        record = run_case(
            case=warmup_case,
            adapter=adapter,
            run_mode="warmup",
            session_id=warmup_session,
            settings=settings,
            allow_repair=False,
            firmware_commit=args.firmware_commit,
            web_commit=args.web_commit,
            asset_manifest_sha256=args.asset_manifest_sha256,
        )
        warmup_store.append(record)
        if record["status"] != "completed":
            print(
                f"formal run blocked because warmup failed for {adapter.provider_id}: "
                f"{record['providerError'] or record['skipReason']}",
                file=sys.stderr,
            )
            return 1

    store = JsonlRunStore(session_id=session_id, mode="formal", root=args.results_root)
    exit_code = 0
    count = 0
    for adapter in adapters.values():
        for case in cases:
            record = run_case(
                case=case,
                adapter=adapter,
                run_mode="formal",
                session_id=session_id,
                settings=settings,
                allow_repair=True,
                firmware_commit=args.firmware_commit,
                web_commit=args.web_commit,
                asset_manifest_sha256=args.asset_manifest_sha256,
            )
            path = store.append(record)
            _print_record_summary(record, path)
            count += 1
            if record["status"] != "completed":
                exit_code = 1
    if count != 18:
        print(f"internal error: formal run wrote {count} records instead of 18", file=sys.stderr)
        return 1
    return exit_code


def show_providers() -> int:
    rows = []
    for provider_id, adapter in default_adapters().items():
        availability = adapter.availability()
        rows.append(
            {
                "providerId": provider_id,
                "requestedModel": adapter.requested_model,
                "deployment": adapter.deployment,
                "schemaMode": adapter.schema_mode,
                "available": availability.available,
                "reason": availability.reason,
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _add_generation_settings(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--session-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m eval.easyinput_eval.cli",
        description="EasyInput AI pattern evaluation harness. No command runs by default.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("inspect", help="validate schemas and benchmark data without network calls")
    subparsers.add_parser("providers", help="show provider/model readiness without generation")

    smoke = subparsers.add_parser(
        "smoke",
        help="run one non-scoring case; defaults to local Ollama only",
    )
    smoke.add_argument("--case", default="G-HOUSE")
    smoke.add_argument(
        "--provider",
        action="append",
        choices=("ollama", "zhipu", "deepseek"),
        help="repeat to test multiple providers; default is ollama",
    )
    smoke.add_argument("--allow-repair", action="store_true")
    _add_generation_settings(smoke)

    formal = subparsers.add_parser(
        "formal",
        help="run the pre-registered 18 outputs after explicit confirmation",
    )
    formal.add_argument("--confirm-formal", required=True)
    formal.add_argument("--firmware-commit", required=True)
    formal.add_argument("--web-commit", required=True)
    formal.add_argument("--asset-manifest-sha256", required=True)
    _add_generation_settings(formal)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "inspect":
        return inspect_contract()
    if args.command == "providers":
        return show_providers()
    if args.command == "smoke":
        return run_smoke(args)
    if args.command == "formal":
        return run_formal(args)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
