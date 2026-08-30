from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """你是 EasyInput 单小节鼓点生成器。你必须严格服从请求中声明的硬件能力：4/4 拍、六条固定轨道、16 个十六分音符步骤、每步只能为整数 0 或 1。不要输出力度、Swing、三连音、微时序、PCM、Mask、S1-S7、GPIO、PPQN、I2S 或 USB 命令。只返回一个符合 easyinput.pattern.v1 的 JSON 对象，不要使用 Markdown 代码块，不要添加 JSON 之外的文字。数组下标 0 对应人类第 1 步，下标 15 对应第 16 步。编辑任务必须严格服从 editPolicy。"""


def build_initial_messages(
    request: dict[str, Any], output_schema: dict[str, Any]
) -> list[dict[str, str]]:
    user_payload = {
        "request": request,
        "outputSchema": output_schema,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def build_repair_messages(
    request: dict[str, Any],
    output_schema: dict[str, Any],
    raw_output: str,
    errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    messages = build_initial_messages(request, output_schema)
    messages.append({"role": "assistant", "content": raw_output})
    repair_payload = {
        "instruction": "上一个输出未通过校验。只根据校验错误修复，并返回完整的 easyinput.pattern.v1 JSON；不要解释，也不要提供多个候选。",
        "validationErrors": errors,
    }
    messages.append(
        {
            "role": "user",
            "content": json.dumps(repair_payload, ensure_ascii=False, separators=(",", ":")),
        }
    )
    return messages
