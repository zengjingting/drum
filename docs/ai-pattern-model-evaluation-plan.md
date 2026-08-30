# AI 鼓点生成模型选型实验方案

状态：实验设计，尚未执行  
版本：v1.0  
日期：2026-08-30

## 1. 实验目标

本实验为 EasyInput 鼓机选择一款能够将中文自然语言稳定转换为板载六音色、单小节 16 步 Pattern 的模型。实验比较一个本地小模型与两个云端低延迟模型，回答三个产品问题：

1. 模型能否首次输出可被网页校验和硬件执行的结构化 Pattern？
2. 在当前无力度、无 Swing、无三连音的 16 步能力内，模型生成的 House、Funk、Country 是否满足指令且具有可接受的律动？
3. 若本地模型的质量接近云端模型，是否可以用离线能力、隐私和零调用成本换取小幅质量差异？

实验只评估 `文字生成 Pattern` 和 `局部修改 Pattern`。以下能力不在本轮范围内：

- 麦克风录音、Beatbox 或 Audio-to-MIDI；
- AI 生成、替换或烧录 PCM 音色；
- 多小节 A/B Pattern；
- 力度、Swing、三连音、微时序；
- AI 解释实体 Pad 演奏风格。

## 2. 当前产品边界

实验必须服从当前已经实现的硬件和协议，不以模型输出扩张固件能力。

| 项目 | 当前合同 |
| --- | --- |
| 节拍网格 | 4/4 拍，单小节 16 步，每步为 1/16 音符 |
| 轨道数 | 6 |
| 触发值 | 每步只能是 0 或 1 |
| BPM | 整数 40–240，未指定时默认 120 |
| 音色 | Kick、Snare、Closed Hi-Hat、Open Hi-Hat、Clap、Rimshot |
| 硬件计时 | 连续 I2S 样本流驱动 96 PPQN；每 24 tick 推进一个 16 分音符步骤 |
| 网页到固件 | 六个 16-bit Mask 通过原子 `PATTERN` 命令下发，收到 ACK 才算应用成功 |
| 不支持 | 力度、Swing、三连音、每步微时序、Tom、Ride |

模型只接触逻辑音色 ID，不接触 S1–S7、GPIO 或 PCM 文件。当前 S3 禁用、Closed Hi-Hat 迁移至 S7，这类实体映射由网页和固件配置负责。

## 3. 候选模型

| 编号 | 模型 | 部署方式 | 本轮角色 |
| --- | --- | --- | --- |
| M1 | `qwen3.5:2b` | 本机 Ollama | 本地小模型基线 |
| M2 | `glm-5.3-flash` | 云端 API | 国产低延迟云模型 |
| M3 | `deepseek-v4-flash` | 云端 API | 国产低延迟云模型 |

模型名称可能是会滚动更新的服务别名。执行时必须保存请求的模型 ID、服务端实际返回的模型版本、调用日期和 API 参数。DeepSeek 本轮请求 ID 为 `deepseek-v4-flash`，预期解析版本为 `DeepSeek-V4-Flash-0731`，但仍以响应中的实际值为准。不同版本不得混在同一次比较中；若服务端版本在实验中途变化，受影响的模型需要整组重跑。

## 4. 系统链路与责任边界

```text
用户自然语言 + 固定硬件能力 + 可选当前 Pattern
                        ↓
                       模型
                        ↓
              easyinput.pattern.v1 JSON
                        ↓
          Schema 校验 + 指令约束校验 + 转 Mask
                        ↓
                 PATTERN 六个 Mask
                        ↓
                 固件 ACK + 硬件播放
```

PCM sample 不属于模型输出。板载 PCM 已经与六个逻辑音色绑定；模型只决定 BPM 和每条轨道在哪些步骤触发。模型也不输出 PPQN、I2S 参数、GPIO、串口命令或 16-bit Mask，避免同一 Pattern 出现两份互相矛盾的表示。

## 5. 模型输入合同

输入 Schema 版本为 `easyinput.pattern-request.v1`。`task` 仅允许 `generate` 或 `edit`。

```json
{
  "schemaVersion": "easyinput.pattern-request.v1",
  "task": "generate",
  "userPrompt": "生成一个 124 BPM 的 House 鼓点",
  "grid": {
    "beatsPerBar": 4,
    "stepsPerBeat": 4,
    "stepsPerBar": 16,
    "humanStepNumbering": "1-16",
    "beatSteps": [1, 5, 9, 13]
  },
  "tempo": {
    "minBpm": 40,
    "maxBpm": 240,
    "defaultBpm": 120
  },
  "instruments": [
    {"trackId": "kick", "name": "底鼓", "role": "低频节奏重心"},
    {"trackId": "snare", "name": "军鼓", "role": "常用于第二和第四拍"},
    {"trackId": "closed_hat", "name": "闭镲", "role": "短促的持续脉冲"},
    {"trackId": "open_hat", "name": "开镲", "role": "较长延音与反拍强调"},
    {"trackId": "clap", "name": "拍手", "role": "电子化拍手强调"},
    {"trackId": "rim", "name": "鼓边击", "role": "尖锐短促的哒声"}
  ],
  "unsupportedFeatures": [
    "velocity",
    "swing",
    "triplet",
    "microtiming",
    "instrumentsOutsideTheList"
  ],
  "currentPattern": null
}
```

`edit` 任务必须携带 `currentPattern`，并在 `editPolicy` 中显式声明允许改变的字段。禁止仅靠自然语言推断哪些轨道可以改。下面仅展示与 `edit` 有关的变化字段；`schemaVersion`、网格、速度范围、音色和不支持能力与完整输入示例相同。

```json
{
  "task": "edit",
  "userPrompt": "只减少底鼓密度，其他内容保持不变",
  "currentPattern": {
    "schemaVersion": "easyinput.pattern.v1",
    "name": "Reference Funk",
    "style": "funk",
    "bpm": 105,
    "tracks": {
      "kick": [1,0,0,1, 0,0,1,0, 1,0,0,1, 0,0,1,0],
      "snare": [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
      "closed_hat": [1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1],
      "open_hat": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
      "clap": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
      "rim": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0]
    }
  },
  "editPolicy": {
    "mutableFields": ["tracks.kick"],
    "immutableFields": [
      "bpm",
      "tracks.snare",
      "tracks.closed_hat",
      "tracks.open_hat",
      "tracks.clap",
      "tracks.rim"
    ]
  }
}
```

## 6. 模型输出合同

输出 Schema 版本为 `easyinput.pattern.v1`。六条轨道必须全部存在，每条恰好包含 16 个整数，且每个整数只能是 0 或 1。数组第一个元素代表人类编号的第 1 步，并转换为 16-bit Mask 的 bit 0；最后一个元素代表第 16 步和 bit 15。

```json
{
  "schemaVersion": "easyinput.pattern.v1",
  "name": "Straight House",
  "style": "house",
  "bpm": 124,
  "tracks": {
    "kick": [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],
    "snare": [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
    "closed_hat": [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
    "open_hat": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
    "clap": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0],
    "rim": [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0]
  },
  "designNote": "四拍底鼓构成稳定重心，八分闭镲维持推进。"
}
```

必填字段为 `schemaVersion`、`name`、`style`、`bpm` 和 `tracks`。`designNote` 为可选展示字段，不参与硬件执行和结构评分。输出不包含以下字段：

- PCM、sample 或 sample ID；
- 16-bit Mask；
- S1–S7 或 GPIO；
- PPQN、I2S 或 USB 命令；
- Swing、力度或微时序；
- 思维链或模型自报置信度。

## 7. 六个实验用例

### 7.1 基础生成

#### G-HOUSE

Prompt：

> 生成一个 124 BPM 的 House 鼓点。底鼓保持四踩，闭镲提供稳定律动，整体适合舞蹈。

自动约束：

- BPM 等于 124；
- Kick 仅在第 1、5、9、13 步触发，总触发数等于 4；
- 六条轨道和 16 步结构合法。

#### G-FUNK

Prompt：

> 生成一个 105 BPM 的 Funk 鼓点。军鼓保持第二、第四拍，底鼓需要有切分，但不要过密。

自动约束：

- BPM 等于 105；
- Snare 的第 5、13 步为 1；
- Kick 总触发数为 3–7；
- Kick 至少有一个触发不在第 1、5、9、13 步；
- 六条轨道和 16 步结构合法。

人工校准参考：[任何架子鼓初学者都可以演奏的 5 种音乐风格](https://www.bilibili.com/video/BV1bmRYYHEiX/)。该视频只作为简化 Funk 的听感锚点，不作为唯一正确 Pattern。

#### G-COUNTRY

Prompt：

> 生成一个 120 BPM 的 Country 鼓点。使用稳定的底鼓、军鼓 Backbeat 和八分音符闭镲，适合初学者演奏。

自动约束：

- BPM 等于 120；
- Snare 的第 5、13 步为 1；
- Closed Hi-Hat 仅在第 1、3、5、7、9、11、13、15 步触发；
- 六条轨道和 16 步结构合法。

人工校准使用与 G-FUNK 相同的视频中的简化 Country 示例。

### 7.2 局部修改

编辑用例使用固定人工参考 Pattern，不使用各模型刚生成的结果。这样三个模型收到完全相同的输入，修改能力不会被上一轮生成质量混淆。产品联调阶段可以另测 `生成后继续修改` 的真实连续对话。

#### E-HOUSE

基准 Pattern：

- BPM 124；
- Kick：第 1、5、9、13 步；
- Snare：第 5、13 步；
- Closed Hi-Hat：第 1、3、5、7、9、11、13、15 步；
- 其他轨道为空。

Prompt：

> 将当前 House Pattern 第 3、7、11、15 步的闭镲替换为开镲。其他步骤、其他轨道和 BPM 必须保持不变。

自动约束：

- Open Hi-Hat 的第 3、7、11、15 步由 0 变为 1；
- Closed Hi-Hat 的相同步骤由 1 变为 0；
- 除上述八个单元格外，所有字段与输入完全相同。

#### E-FUNK

基准 Pattern 使用第 5 节 `edit` 输入示例。

Prompt：

> 减少当前 Funk Pattern 的底鼓密度，但保留切分感。军鼓、闭镲、其他轨道和 BPM 必须保持不变。

自动约束：

- Kick 触发数少于输入 Pattern；
- Kick 至少保留一个非正拍触发；
- BPM 和其他五条轨道逐值等于输入；
- 六条轨道和 16 步结构合法。

#### E-COUNTRY

基准 Pattern：

- BPM 120；
- Kick：第 1、9 步；
- Snare：第 5、13 步；
- Closed Hi-Hat：第 1、3、5、7、9、11、13、15 步；
- 其他轨道为空。

Prompt：

> 在当前 Country Pattern 的最后四步加入简化 Fill。只能修改 Kick、Snare 和 Rim 的第 13–16 步；前 12 步、其他轨道和 BPM 必须保持不变。

自动约束：

- 前 12 步逐值等于输入；
- Closed Hi-Hat、Open Hi-Hat 和 Clap 全部逐值等于输入；
- BPM 等于 120；
- 第 13–16 步的 Kick、Snare、Rim 合计至少有三个触发；
- Rim 在第 13–16 步至少有一个触发。

## 8. 执行规模和统一条件

主实验为 6 个用例乘以 3 个模型，共 18 个首次输出。每个用例每个模型只运行一次，不通过重复采样挑选最好结果。

统一条件如下：

- 使用同一份 system prompt、输入 Schema、输出 Schema 和六个用例；
- 优先使用非思考模式；`glm-5.3-flash` 当前只支持开启思考，因此固定为其最低可用档 `reasoning_effort=low`，并把该差异写入调用记录；
- 温度建议固定为 0.6，`top_p` 建议固定为 0.9；
- 最大输出长度固定为 1024 tokens；`glm-5.3-flash` 强制开启思考，使用更短上限可能在最终 JSON 前截断；
- 对话调用无历史上下文，每个用例独立发送；
- 原生结构化输出可用时启用 JSON Schema；不可用时使用同一 Schema 的 prompt 约束，并记录 `schemaMode`；
- 正式计时前，每个模型执行一次不计分预热；
- 本地模型另外记录冷启动加载时间；
- 云端延迟包含网络传输，代表当前产品实际调用体验；
- 三个模型使用同一块开发板、同一固件 commit、同一网页 commit、同一组 PCM 资产、同一供电和扬声器音量。

若某个 API 不支持温度、`top_p` 或非思考模式，不伪造等价参数。实验记录中标为 `unsupported`，并把该差异作为产品栈能力的一部分保留。

## 9. 校验、修复和硬件播放

模型原始输出先经过以下校验：

1. JSON 可解析；
2. Schema 版本正确；
3. BPM 是 40–240 的整数；
4. 仅包含六个允许的轨道；
5. 六条轨道全部存在；
6. 每条轨道恰好 16 个整数；
7. 每个步骤只能为 0 或 1；
8. 整个 Pattern 不得全为空；
9. 用例的自动约束全部逐项计算；
10. 数组可唯一转换为六个 16-bit Mask；
11. 固件收到 `PATTERN` 后返回 ACK。

首次输出失败时，记录 `firstPassValid=false`，并允许一次结构修复。修复输入只包含原始输出和明确的校验错误，不提供正确答案。修复成功可以继续硬件试听，但不能覆盖首次失败记录。第二次仍失败时停止该条用例，不向硬件发送无效数据。

## 10. 指标与评分

总分为 100 分。所有评分规则在运行前冻结。

### 10.1 结构与硬件合法性：30 分

- 首次 JSON 可解析：5 分；
- 首次 Schema 完全合法：10 分；
- 自动转换为 Mask：5 分；
- 固件返回 PATTERN ACK：10 分。

模型该项得分为六个用例的平均值。

### 10.2 用户指令满足度：30 分

汇总六个用例中所有非结构性自动约束，按 `通过项数 / 适用约束总数` 计算，通过比例乘以 30。JSON、轨道数量、数组长度和 Mask 转换只进入结构评分，不在指令评分重复计分。

涉及 `切分感`、`适合舞蹈` 等不能仅靠规则判断的要求，进入人工试听，不冒充自动指标。

### 10.3 风格与律动盲听：30 分

每个合法结果通过当前板载 PCM 播放。试听页面隐藏模型名称并随机化 A/B/C 顺序。评价者对每条结果给出三个 1–5 分评分：

- 风格辨识度；
- 律动自然度；
- 直接应用意愿。

三个评分先在单条结果内取平均，再对模型的所有合法结果取平均。最终按 `(平均分 - 1) / 4 × 30` 换算，1 分对应 0 分，5 分对应 30 分。编辑任务同时试听修改前后版本，但只对修改后的结果打分。B站示例仅用于 Funk 和 Country 的人工校准，不作为逐音符标准答案。

若本轮只有一名评价者，报告必须标记为单人 pilot，不得把分数包装为普遍用户偏好。

### 10.4 完整合法 Pattern 延迟：10 分

主延迟从请求发出开始，到首次收到可解析且 Schema 合法的完整 Pattern 为止。只出现首 Token 不算完成。六条用例取中位数：

| 中位延迟 | 得分 |
| --- | ---: |
| 不超过 2 秒 | 10 |
| 大于 2 秒且不超过 3 秒 | 8 |
| 大于 3 秒且不超过 5 秒 | 6 |
| 大于 5 秒且不超过 8 秒 | 3 |
| 大于 8 秒，或超过一次修复仍失败 | 0 |

同时原样报告首 Token 延迟、完整响应延迟和修复后延迟，不只展示换算分数。

## 11. 选型规则

模型必须先满足两个硬门槛：

1. 六个用例中至少五个首次通过 Schema，且修复后六个全部合法；
2. 不得把未通过校验的 Pattern 发送给硬件。

通过门槛后按总分排序。若本地模型与最高分云端模型的总分差不超过 5 分，优先选择本地模型。该规则将离线能力、隐私和零调用成本视为明确的产品收益，而不是事后解释。

若前两名相差不超过 5 分，进入一次补测：只选择区分度最高的三个用例，对前两名各重跑一次，最多增加 6 个输出。补测结果单独报告，不与首次 18 个输出混写。

## 12. 实验记录结构

每次调用至少保存以下字段：

```json
{
  "experimentVersion": "easyinput-groove-eval.v1",
  "runId": "2026-08-30-M1-G-HOUSE-01",
  "caseId": "G-HOUSE",
  "requestedModel": "qwen3.5:2b",
  "responseReportedModel": "待运行时记录",
  "documentedModelVersion": null,
  "modelVersionEvidence": "response_reports_requested_model",
  "deployment": "local_ollama",
  "schemaMode": "json_schema",
  "thinkingMode": "disabled",
  "temperature": 0.6,
  "topP": 0.9,
  "maxOutputTokens": 1024,
  "startedAt": "待运行时记录",
  "firstTokenLatencyMs": null,
  "completeResponseLatencyMs": null,
  "firstValidPatternLatencyMs": null,
  "rawOutput": null,
  "parsedPattern": null,
  "firstPassValid": null,
  "validationErrors": [],
  "repairAttempted": false,
  "repairValid": null,
  "patternMasks": null,
  "hardwareAck": null,
  "humanRating": {
    "blindOrder": null,
    "styleRecognition": null,
    "grooveNaturalness": null,
    "willingnessToUse": null
  },
  "firmwareCommit": "待运行时记录",
  "webCommit": "待运行时记录",
  "assetManifestSha256": "待运行时记录"
}
```

原始输出、解析结果和校验错误必须同时保存。只保存最终 Pattern 会丢失模型首次失败、修复和格式稳定性证据。

## 13. 执行顺序

1. 固化 `pattern-request` 和 `pattern` JSON Schema；
2. 将六个用例及固定编辑基准 Pattern 保存为机器可读数据；
3. 实现统一调用适配层和结果日志；
4. 实现确定性 Schema、约束和 Pattern Mask 校验；
5. 固化固件、网页和 PCM 资产版本；
6. 预热三个模型并执行 18 次首次调用；
7. 对合法结果依次下发开发板并记录 ACK；
8. 隐藏模型名称，随机顺序完成硬件盲听；
9. 计算硬指标、人工评分和总分；
10. 按预注册门槛选型，必要时触发最多 6 次补测；
11. 将实测结果写入独立结果报告，不回填或改写本方案中的预注册规则。

## 14. 结果报告边界

本文件是实验设计，不包含任何实测结论。后续结果报告应明确区分：

- 预注册规则；
- 原始模型输出；
- 自动校验结果；
- 单人或多人盲听结果；
- 真机 ACK 和播放事实；
- 模型选型结论；
- 尚未验证的长期稳定性和用户偏好。

18 个首次输出足以支持一次产品原型选型，不足以声称模型具有普遍音乐审美，也不足以形成统计显著的用户研究结论。

## 15. 方案依据

当前硬件和协议边界以仓库实现为准：

- [`README.md`](../README.md)：当前板型、音色映射、16 步音序器和 USB 协议说明；
- [`main/board_pins.h`](../main/board_pins.h)：96 PPQN、默认 BPM 和 BPM 范围；
- [`main/metronome_app.c`](../main/metronome_app.c)：每 24 PPQN tick 推进一个 16 分音符步骤；
- [`main/usb_serial_control.c`](../main/usb_serial_control.c)：原子 `PATTERN` 命令和 ACK；
- [任何架子鼓初学者都可以演奏的 5 种音乐风格](https://www.bilibili.com/video/BV1bmRYYHEiX/)：Funk 和 Country 的人工听感校准素材。

本文件中的输入输出结构目前是待实现合同，不代表对应的机器可读 JSON Schema、调用适配层或实验日志已经完成。
