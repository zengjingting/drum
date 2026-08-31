#!/usr/bin/env python3
"""Local-only web server and DeepSeek proxy for the EasyInput drum UI."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from eval.easyinput_eval.cases import load_benchmark_document
from eval.easyinput_eval.constants import MAX_BPM, MIN_BPM, STEPS_PER_BAR, TRACK_IDS
from eval.easyinput_eval.masks import masks_as_firmware_order
from eval.easyinput_eval.prompts import build_initial_messages, build_repair_messages
from eval.easyinput_eval.providers import (
    Availability,
    GenerationSettings,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
    default_adapters,
)
from eval.easyinput_eval.runner import load_output_schema
from eval.easyinput_eval.validation import (
    parse_pattern_json,
    validate_pattern,
    validate_request,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "main" / "web"
EXPLANATION_SCHEMA_PATH = ROOT / "schemas" / "pattern-explanation.schema.json"
LOCAL_ENV_PATH = ROOT / ".env.local"
MAX_REQUEST_BYTES = 16 * 1024
MODEL_ID = "deepseek-v4-flash"
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CJK_TEXT_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
RECORDING_TRACE_PATH = ROOT / ".diagnostics" / "recording-trace.ndjson"
TRACE_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TRACE_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:authorization|api.?key|prompt|secret|token|password)", re.IGNORECASE
)
TRACE_STAGES = {
    "record_start_requested",
    "record_boundary_started",
    "pad_received",
    "record_stop_requested",
    "record_boundary_stopped",
    "recording_verified",
    "pattern_quantized",
    "pattern_sync_sent",
    "pattern_ack_received",
    "playback_toggle_requested",
    "device_state",
    "recording_error",
    "record_button_state",
    "pattern_save_requested",
    "pattern_save_completed",
    "pattern_save_failed",
}


def _load_local_environment(path: Path = LOCAL_ENV_PATH) -> None:
    """Load local defaults without overriding the launching environment."""
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not ENV_KEY_PATTERN.fullmatch(key):
            raise RuntimeError(
                f"Invalid local environment entry at {path.name}:{line_number}"
            )

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


class PublicApiError(RuntimeError):
    def __init__(self, error_type: str, message: str, status: HTTPStatus) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status = status


def _validate_trace_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        raise PublicApiError(
            "request_error", "诊断数据嵌套过深。", HTTPStatus.BAD_REQUEST
        )
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not value == value or value in {float("inf"), float("-inf")}:
            raise PublicApiError(
                "request_error", "诊断数值不合法。", HTTPStatus.BAD_REQUEST
            )
        return value
    if isinstance(value, str):
        if len(value) > 256:
            raise PublicApiError(
                "request_error", "诊断文本过长。", HTTPStatus.BAD_REQUEST
            )
        return value
    if isinstance(value, list):
        if len(value) > 128:
            raise PublicApiError(
                "request_error", "诊断数组过长。", HTTPStatus.BAD_REQUEST
            )
        return [_validate_trace_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                raise PublicApiError(
                    "request_error", "诊断字段名不合法。", HTTPStatus.BAD_REQUEST
                )
            if TRACE_SENSITIVE_KEY_PATTERN.search(key):
                raise PublicApiError(
                    "request_error", "诊断数据不能包含敏感字段。", HTTPStatus.BAD_REQUEST
                )
            normalized[key] = _validate_trace_value(item, depth=depth + 1)
        return normalized
    raise PublicApiError(
        "request_error", "诊断数据类型不受支持。", HTTPStatus.BAD_REQUEST
    )


def _validate_trace_event(value: Any) -> dict[str, Any]:
    required = {"sessionId", "sequence", "stage", "clientTimeMs", "payload"}
    if not isinstance(value, dict) or set(value) != required:
        raise PublicApiError(
            "request_error", "诊断事件字段集合不匹配。", HTTPStatus.BAD_REQUEST
        )
    session_id = value.get("sessionId")
    if not isinstance(session_id, str) or not TRACE_SESSION_PATTERN.fullmatch(session_id):
        raise PublicApiError(
            "request_error", "诊断会话编号不合法。", HTTPStatus.BAD_REQUEST
        )
    sequence = value.get("sequence")
    client_time_ms = value.get("clientTimeMs")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise PublicApiError(
            "request_error", "诊断序号不合法。", HTTPStatus.BAD_REQUEST
        )
    if (
        not isinstance(client_time_ms, int)
        or isinstance(client_time_ms, bool)
        or client_time_ms < 0
    ):
        raise PublicApiError(
            "request_error", "诊断客户端时间不合法。", HTTPStatus.BAD_REQUEST
        )
    stage = value.get("stage")
    if stage not in TRACE_STAGES:
        raise PublicApiError(
            "request_error", "诊断阶段不受支持。", HTTPStatus.BAD_REQUEST
        )
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise PublicApiError(
            "request_error", "诊断 payload 必须是对象。", HTTPStatus.BAD_REQUEST
        )
    return {
        "sessionId": session_id,
        "sequence": sequence,
        "stage": stage,
        "clientTimeMs": client_time_ms,
        "payload": _validate_trace_value(payload),
    }


class RecordingTraceStore:
    def __init__(self, path: Path = RECORDING_TRACE_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, raw_event: Any) -> dict[str, Any]:
        event = _validate_trace_event(raw_event)
        stored = {"serverTimeMs": time.time_ns() // 1_000_000, **event}
        encoded = json.dumps(stored, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(encoded + "\n")
        return stored

    def read(self, session_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if session_id is not None and not TRACE_SESSION_PATTERN.fullmatch(session_id):
            raise PublicApiError(
                "request_error", "诊断会话编号不合法。", HTTPStatus.BAD_REQUEST
            )
        if not self.path.is_file():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        events: list[dict[str, Any]] = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id is None or event.get("sessionId") == session_id:
                events.append(event)
        return events[-max(1, min(limit, 500)):]


def _generate_request(user_prompt: str) -> dict[str, Any]:
    defaults = copy.deepcopy(load_benchmark_document()["requestDefaults"])
    defaults.update(
        {
            "task": "generate",
            "userPrompt": user_prompt,
            "currentPattern": None,
        }
    )
    validation = validate_request(defaults)
    if not validation.schema_valid:
        raise RuntimeError(f"internal request contract is invalid: {validation.errors_as_dicts()}")
    return defaults


def _validate_output(raw_output: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    pattern, parse_issues = parse_pattern_json(raw_output)
    if parse_issues:
        return None, [issue.to_dict() for issue in parse_issues]
    validation = validate_pattern(pattern)
    if not validation.valid:
        return pattern, validation.errors_as_dicts()
    return pattern, []


def _load_explanation_schema() -> dict[str, Any]:
    return json.loads(EXPLANATION_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_explanation_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "bpm", "tracks", "approximateQuantization"
    }:
        raise PublicApiError(
            "request_error",
            "解释请求必须且只能包含 bpm、tracks 和 approximateQuantization。",
            HTTPStatus.BAD_REQUEST,
        )
    bpm = value.get("bpm")
    if not isinstance(bpm, int) or isinstance(bpm, bool) or not MIN_BPM <= bpm <= MAX_BPM:
        raise PublicApiError(
            "request_error", "BPM 必须是 40–240 的整数。", HTTPStatus.BAD_REQUEST
        )
    if not isinstance(value.get("approximateQuantization"), bool):
        raise PublicApiError(
            "request_error",
            "approximateQuantization 必须是布尔值。",
            HTTPStatus.BAD_REQUEST,
        )
    tracks = value.get("tracks")
    if not isinstance(tracks, dict) or set(tracks) != set(TRACK_IDS):
        raise PublicApiError(
            "request_error", "tracks 必须且只能包含六条固定音轨。", HTTPStatus.BAD_REQUEST
        )
    normalized_tracks: dict[str, list[int]] = {}
    trigger_count = 0
    for track_id in TRACK_IDS:
        steps = tracks.get(track_id)
        if (
            not isinstance(steps, list)
            or len(steps) != STEPS_PER_BAR
            or any(type(step) is not int or step not in (0, 1) for step in steps)
        ):
            raise PublicApiError(
                "request_error",
                f"{track_id} 必须包含 16 个整数 0 或 1。",
                HTTPStatus.BAD_REQUEST,
            )
        normalized_tracks[track_id] = list(steps)
        trigger_count += sum(steps)
    if trigger_count == 0:
        raise PublicApiError(
            "request_error", "空 Pattern 无法进行风格解释。", HTTPStatus.BAD_REQUEST
        )
    return {
        "bpm": bpm,
        "tracks": normalized_tracks,
        "approximateQuantization": value["approximateQuantization"],
    }


def _extract_rhythm_features(pattern: dict[str, Any]) -> dict[str, Any]:
    tracks = pattern["tracks"]
    active_steps = {
        track_id: [index + 1 for index, value in enumerate(tracks[track_id]) if value]
        for track_id in TRACK_IDS
    }
    quarter_steps = {1, 5, 9, 13}
    backbeat_steps = {5, 13}
    return {
        "triggerCounts": {
            track_id: len(active_steps[track_id]) for track_id in TRACK_IDS
        },
        "activeSteps": active_steps,
        "kickOffQuarterSteps": [
            step for step in active_steps["kick"] if step not in quarter_steps
        ],
        "snareBackbeatSteps": [
            step for step in active_steps["snare"] if step in backbeat_steps
        ],
        "hatSubdivision": (
            "sixteenth"
            if len(active_steps["closed_hat"]) >= 12
            else "eighth"
            if len(active_steps["closed_hat"]) >= 6
            else "sparse"
        ),
        "lastQuarterActivity": sum(
            tracks[track_id][step]
            for track_id in TRACK_IDS
            for step in range(12, 16)
        ),
    }


def _build_explanation_messages(
    pattern: dict[str, Any],
    features: dict[str, Any],
    schema: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        "你是 EasyInput 实体鼓机的节奏解释助手。只依据提供的六轨单小节 16 步 Pattern "
        "和确定性特征判断节奏风格倾向。不得声称读取了音频，不得判断完整歌曲流派。"
        "证据必须引用输入中实际为 1 的音轨和 1-based 步数。置信度只能是 high、medium、low。"
        "summary、evidence.reason、suggestion、limitations 必须使用简体中文；"
        "style 可以保留 Rock、Hip-Hop 等通用风格名称。"
        "只输出符合给定 JSON Schema 的 JSON 对象，不要 Markdown。\nSchema:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    user = json.dumps(
        {"pattern": pattern, "features": features},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _validate_explanation(
    raw_output: str, pattern: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        value = json.loads(raw_output)
    except json.JSONDecodeError:
        return None, [{"path": "$", "message": "输出不是合法 JSON。"}]
    errors: list[dict[str, str]] = []
    if not isinstance(value, dict):
        return None, [{"path": "$", "message": "解释必须是 JSON 对象。"}]
    allowed = {
        "schemaVersion", "summary", "styleCandidates", "evidence", "suggestion", "limitations"
    }
    required = set(allowed)
    if set(value) != required:
        errors.append({"path": "$", "message": "解释字段集合不匹配。"})
    if value.get("schemaVersion") != "easyinput.pattern.explanation.v1":
        errors.append({"path": "$.schemaVersion", "message": "Schema 版本不匹配。"})
    for field, limit in (("summary", 300), ("suggestion", 300), ("limitations", 300)):
        text = value.get(field)
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            errors.append({"path": f"$.{field}", "message": f"{field} 文本不合法。"})
        elif not CJK_TEXT_PATTERN.search(text):
            errors.append({
                "path": f"$.{field}",
                "message": f"{field} 必须使用简体中文。",
            })
    candidates = value.get("styleCandidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        errors.append({"path": "$.styleCandidates", "message": "风格候选必须为 1–3 个。"})
    else:
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or set(candidate) != {"style", "confidence"}:
                errors.append({"path": f"$.styleCandidates[{index}]", "message": "候选字段不合法。"})
                continue
            if (
                not isinstance(candidate["style"], str)
                or not candidate["style"].strip()
                or len(candidate["style"]) > 40
                or candidate["confidence"] not in {"high", "medium", "low"}
            ):
                errors.append({"path": f"$.styleCandidates[{index}]", "message": "候选内容不合法。"})
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 6:
        errors.append({"path": "$.evidence", "message": "判断依据必须为 1–6 条。"})
    else:
        for index, item in enumerate(evidence):
            path = f"$.evidence[{index}]"
            if not isinstance(item, dict) or set(item) != {"track", "steps", "reason"}:
                errors.append({"path": path, "message": "依据字段不合法。"})
                continue
            track = item.get("track")
            steps = item.get("steps")
            reason = item.get("reason")
            if track not in TRACK_IDS:
                errors.append({"path": f"{path}.track", "message": "依据音轨不合法。"})
                continue
            if (
                not isinstance(steps, list)
                or not 1 <= len(steps) <= 16
                or len(steps) != len(set(steps))
                or any(type(step) is not int or not 1 <= step <= 16 for step in steps)
            ):
                errors.append({"path": f"{path}.steps", "message": "依据步数不合法。"})
            else:
                inactive = [step for step in steps if pattern["tracks"][track][step - 1] != 1]
                if inactive:
                    errors.append({
                        "path": f"{path}.steps",
                        "message": f"引用了未触发步数 {inactive}。",
                    })
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
                errors.append({"path": f"{path}.reason", "message": "依据说明不合法。"})
            elif not CJK_TEXT_PATTERN.search(reason):
                errors.append({
                    "path": f"{path}.reason",
                    "message": "依据说明必须使用简体中文。",
                })
    return value, errors


def _build_explanation_repair_messages(
    pattern: dict[str, Any],
    features: dict[str, Any],
    schema: dict[str, Any],
    first_output: str,
    errors: list[dict[str, str]],
) -> list[dict[str, str]]:
    messages = _build_explanation_messages(pattern, features, schema)
    messages.extend(
        [
            {"role": "assistant", "content": first_output},
            {
                "role": "user",
                "content": (
                    "上一次输出未通过校验。只修复以下错误，仍然只输出 JSON：\n"
                    + json.dumps(errors, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]
    )
    return messages


class PatternService:
    def __init__(
        self,
        adapter: ProviderAdapter | None = None,
        settings: GenerationSettings | None = None,
        *,
        mock_mode: bool = False,
    ) -> None:
        self.adapter = adapter or default_adapters()["deepseek"]
        self.settings = settings or GenerationSettings()
        self.mock_mode = mock_mode
        if self.adapter.requested_model != MODEL_ID and not mock_mode:
            raise ValueError(f"runtime model must be {MODEL_ID}")
        if self.adapter.thinking_mode != "disabled":
            raise ValueError("P0 runtime must keep DeepSeek thinking disabled")

    def health(self) -> dict[str, Any]:
        available = self.adapter.availability().available
        return {
            "ok": True,
            "service": "easyinput-ai-pattern",
            "model": self.adapter.requested_model,
            "thinkingMode": self.adapter.thinking_mode,
            "configured": available,
            "mock": self.mock_mode,
        }

    def generate(self, user_prompt: str) -> dict[str, Any]:
        if not isinstance(user_prompt, str):
            raise PublicApiError(
                "request_error", "prompt 必须是文本。", HTTPStatus.BAD_REQUEST
            )
        prompt = user_prompt.strip()
        if not prompt:
            raise PublicApiError("request_error", "请输入鼓点描述。", HTTPStatus.BAD_REQUEST)
        if len(prompt) > 500:
            raise PublicApiError(
                "request_error", "鼓点描述不能超过 500 个字符。", HTTPStatus.BAD_REQUEST
            )
        if not self.adapter.availability().available:
            raise PublicApiError(
                "configuration_error",
                "本地 AI 服务尚未配置 DEEPSEEK_API_KEY。",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        request = _generate_request(prompt)
        schema = load_output_schema()
        started = time.perf_counter()
        first_response = self._call(
            messages=build_initial_messages(request, schema), output_schema=schema
        )
        first_pattern, first_errors = _validate_output(first_response.raw_output)
        first_valid = not first_errors
        repair_response: ProviderResponse | None = None
        final_pattern = first_pattern
        final_errors = first_errors

        if not first_valid:
            repair_response = self._call(
                messages=build_repair_messages(
                    request,
                    schema,
                    first_response.raw_output,
                    first_errors,
                ),
                output_schema=schema,
            )
            final_pattern, final_errors = _validate_output(repair_response.raw_output)

        if final_pattern is None or final_errors:
            raise PublicApiError(
                "validation_error",
                "模型输出在一次修复后仍未通过硬件 Pattern 校验，请换一种描述重试。",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        masks = masks_as_firmware_order(final_pattern)
        total_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "model": {
                "requested": self.adapter.requested_model,
                "reported": (
                    repair_response.response_reported_model
                    if repair_response is not None
                    else first_response.response_reported_model
                ),
                "thinkingMode": self.adapter.thinking_mode,
                "mock": self.mock_mode,
            },
            "latencyMs": {
                "firstToken": first_response.first_token_latency_ms,
                "firstResponse": first_response.complete_response_latency_ms,
                "repairFirstToken": (
                    repair_response.first_token_latency_ms if repair_response else None
                ),
                "repairResponse": (
                    repair_response.complete_response_latency_ms if repair_response else None
                ),
                "total": total_ms,
            },
            "firstPass": {
                "valid": first_valid,
                "errors": first_errors,
            },
            "repairAttempted": repair_response is not None,
            "pattern": final_pattern,
            "masks": masks,
        }

    def explain(self, raw_pattern: Any) -> dict[str, Any]:
        pattern = _validate_explanation_request(raw_pattern)
        if not self.adapter.availability().available:
            raise PublicApiError(
                "configuration_error",
                "本地 AI 服务尚未配置 DEEPSEEK_API_KEY。",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        schema = _load_explanation_schema()
        features = _extract_rhythm_features(pattern)
        started = time.perf_counter()
        first_response = self._call(
            messages=_build_explanation_messages(pattern, features, schema),
            output_schema=schema,
        )
        explanation, first_errors = _validate_explanation(
            first_response.raw_output, pattern
        )
        first_valid = not first_errors
        repair_response: ProviderResponse | None = None
        final_errors = first_errors

        if not first_valid:
            repair_response = self._call(
                messages=_build_explanation_repair_messages(
                    pattern,
                    features,
                    schema,
                    first_response.raw_output,
                    first_errors,
                ),
                output_schema=schema,
            )
            explanation, final_errors = _validate_explanation(
                repair_response.raw_output, pattern
            )

        if explanation is None or final_errors:
            raise PublicApiError(
                "validation_error",
                "模型解释在一次修复后仍未通过证据校验，请稍后重试。",
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )

        total_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "model": {
                "requested": self.adapter.requested_model,
                "reported": (
                    repair_response.response_reported_model
                    if repair_response is not None
                    else first_response.response_reported_model
                ),
                "thinkingMode": self.adapter.thinking_mode,
                "mock": self.mock_mode,
            },
            "latencyMs": {
                "firstToken": first_response.first_token_latency_ms,
                "firstResponse": first_response.complete_response_latency_ms,
                "repairFirstToken": (
                    repair_response.first_token_latency_ms if repair_response else None
                ),
                "repairResponse": (
                    repair_response.complete_response_latency_ms if repair_response else None
                ),
                "total": total_ms,
            },
            "firstPass": {"valid": first_valid, "errors": first_errors},
            "repairAttempted": repair_response is not None,
            "features": features,
            "explanation": explanation,
        }

    def _call(
        self, *, messages: list[dict[str, str]], output_schema: dict[str, Any]
    ) -> ProviderResponse:
        try:
            return self.adapter.generate(
                messages=messages,
                output_schema=output_schema,
                settings=self.settings,
            )
        except ProviderError as exc:
            raise PublicApiError(
                "model_error",
                "DeepSeek 调用失败，请检查网络或稍后重试。",
                HTTPStatus.BAD_GATEWAY,
            ) from exc


class MockDeepSeekAdapter(ProviderAdapter):
    provider_id = "deepseek"
    requested_model = MODEL_ID
    deployment = "local_mock"
    schema_mode = "json_object"
    thinking_mode = "disabled"

    def availability(self) -> Availability:
        return Availability(True)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        settings: GenerationSettings,
    ) -> ProviderResponse:
        del output_schema, settings
        is_explanation = any(
            "easyinput.pattern.explanation.v1" in message.get("content", "")
            for message in messages
        )
        pattern = {
            "schemaVersion": "easyinput.pattern.v1",
            "name": "Mock House",
            "style": "House",
            "bpm": 124,
            "tracks": {
                "kick": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                "snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
                "closed_hat": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
                "open_hat": [0] * 16,
                "clap": [0] * 16,
                "rim": [0] * 16,
            },
            "designNote": "本地 mock 仅用于验证页面状态与串口应用链路。",
        }
        explanation_pattern: dict[str, Any] | None = None
        if is_explanation:
            for message in messages:
                try:
                    parsed = json.loads(message.get("content", ""))
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict) and isinstance(parsed.get("pattern"), dict):
                    explanation_pattern = parsed["pattern"]
                    break
        evidence_track = "kick"
        evidence_steps = [1]
        if explanation_pattern is not None:
            for track_id in TRACK_IDS:
                active = [
                    index + 1
                    for index, value in enumerate(explanation_pattern["tracks"][track_id])
                    if value
                ]
                if active:
                    evidence_track = track_id
                    evidence_steps = active[:4]
                    break
        explanation = {
            "schemaVersion": "easyinput.pattern.explanation.v1",
            "summary": "这个单小节鼓点呈现出稳定、直接的基础律动。",
            "styleCandidates": [{"style": "Rock", "confidence": "medium"}],
            "evidence": [
                {
                    "track": evidence_track,
                    "steps": evidence_steps,
                    "reason": "这些实际触发位置构成了当前 Pattern 的主要节奏骨架。",
                }
            ],
            "suggestion": "可以移动一个底鼓落点，比较修改前后的切分感。",
            "limitations": "判断只依据单小节六轨 Pattern，不代表完整歌曲流派。",
        }
        return ProviderResponse(
            raw_output=json.dumps(
                explanation if is_explanation else pattern,
                ensure_ascii=False,
            ),
            response_reported_model="mock-deepseek-v4-flash",
            first_token_latency_ms=20,
            complete_response_latency_ms=40,
            response_metadata={},
        )


def make_handler(
    service: PatternService,
    web_root: Path = WEB_ROOT,
    trace_store: RecordingTraceStore | None = None,
):
    recording_traces = trace_store or RecordingTraceStore()

    class EasyInputHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._write_json(HTTPStatus.OK, service.health())
                return
            if parsed.path == "/api/debug/recording-trace":
                query = parse_qs(parsed.query)
                session_id = query.get("sessionId", [None])[0]
                try:
                    events = recording_traces.read(session_id=session_id)
                except PublicApiError as exc:
                    self._write_public_error(exc)
                    return
                self._write_json(
                    HTTPStatus.OK,
                    {"ok": True, "sessionId": session_id, "events": events},
                )
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            if parsed.path not in {
                "/api/pattern/generate",
                "/api/pattern/explain",
                "/api/debug/recording-trace",
            }:
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": {"type": "not_found", "message": "接口不存在。"}},
                )
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                self._write_public_error(
                    PublicApiError(
                        "request_error", "请求大小不合法。", HTTPStatus.BAD_REQUEST
                    )
                )
                return
            try:
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write_public_error(
                    PublicApiError(
                        "request_error", "请求必须是合法 JSON。", HTTPStatus.BAD_REQUEST
                    )
                )
                return
            try:
                if parsed.path == "/api/debug/recording-trace":
                    event = recording_traces.append(body)
                    result = {
                        "ok": True,
                        "sessionId": event["sessionId"],
                        "sequence": event["sequence"],
                    }
                elif parsed.path == "/api/pattern/generate":
                    if not isinstance(body, dict) or set(body) != {"prompt"}:
                        raise PublicApiError(
                            "request_error",
                            "生成请求只能包含 prompt 字段。",
                            HTTPStatus.BAD_REQUEST,
                        )
                    result = service.generate(body.get("prompt", ""))
                elif parsed.path == "/api/pattern/explain":
                    if not isinstance(body, dict) or set(body) != {"pattern"}:
                        raise PublicApiError(
                            "request_error",
                            "解释请求只能包含 pattern 字段。",
                            HTTPStatus.BAD_REQUEST,
                        )
                    result = service.explain(body.get("pattern"))
            except PublicApiError as exc:
                self._write_public_error(exc)
                return
            except Exception:
                self._write_public_error(
                    PublicApiError(
                        "server_error", "本地 AI 服务发生错误。", HTTPStatus.INTERNAL_SERVER_ERROR
                    )
                )
                return
            self._write_json(HTTPStatus.OK, result)

        def _write_public_error(self, exc: PublicApiError) -> None:
            self._write_json(
                exc.status,
                {
                    "ok": False,
                    "error": {"type": exc.error_type, "message": exc.message},
                },
            )

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            # The stdlib access log includes only method/path/status. Request bodies,
            # prompts, model output, and credentials are never logged here.
            super().log_message(format, *args)

    return EasyInputHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyInput local AI web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mock", action="store_true", help="use a local deterministic mock")
    args = parser.parse_args()

    _load_local_environment()
    adapter: ProviderAdapter | None = MockDeepSeekAdapter() if args.mock else None
    service = PatternService(adapter=adapter, mock_mode=args.mock)
    trace_store = RecordingTraceStore()
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(service, trace_store=trace_store)
    )
    mode = "mock" if args.mock else "DeepSeek"
    configured = "yes" if service.health()["configured"] else "no"
    print(
        f"EasyInput web: http://{args.host}:{args.port}/ "
        f"mode={mode} api_configured={configured}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
