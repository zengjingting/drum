# EasyInput AI 鼓机：AI 解释鼓点 v2 优化方案

日期：2026-08-31

状态：产品与数据合同方案已形成，尚未按本方案修改代码或完成模型、网页和真机验收

适用范围：用户通过实体 Pad录制、网页手动编排或 AI生成得到六轨16步 Pattern后，点击
“AI解释”获得面向鼓点编排初学者的风格讲解与练习建议。

当前实现基线：`easyinput.pattern.explanation.v1`。本文件定义目标版本
`easyinput.pattern.explanation.v2`，不把目标设计表述为当前能力。

## 1. 优化背景

当前 v1将 AI定位为“节奏解释助手”，输出风格候选、置信度、判断依据、修改建议和局限性。
这套结构能够约束模型引用真实音序格，但前端信息组织仍偏向分类报告：

- 用户首先看到多个风格候选和置信度，学习重点不突出；
- 判断依据解释了“为什么像”，但没有系统介绍该风格通常如何编排；
- 单条修改建议没有明确说明预期听感与学习目标；
- `limitations`每次展示会打断创作体验，系统边界更适合保留在后台提示词和校验规则中；
- 当前角色不能充分体现“让初学者在自由创作中学习鼓点风格”的产品定位。

本轮优化将产品角色改为“鼓点编排初学者的智能学习助手”。核心价值从“给 Pattern贴标签”
调整为：

```text
用户自由创作
→ AI指出最接近的一种风格
→ 用当前真实落点解释原因
→ 科普该风格的常见编排规律
→ 给出一次当前设备能够实践的小练习
```

## 2. 产品目标与边界

### 2.1 目标

1. 第一屏直接告诉用户当前节奏最接近的一种风格。
2. 使用当前 Pattern中真实亮起的音轨和步数解释判断原因。
3. 增加一段面向初学者的“风格小课堂”，解释典型鼓组分工、常见落点和律动特点。
4. 给出1至2条当前六轨16步音序器能够实践的建议，并解释预期听感和学习目标。
5. 保持 AI与硬件实时链路解耦；解释失败不得影响 Pattern编辑、保存或硬件播放。
6. 继续以 Pattern revision冻结请求，旧响应不得覆盖更新后的 Pattern。

### 2.2 本轮不做

- 不使用音频理解模型，也不向模型发送录音；
- 不让 AI判断完整歌曲流派；
- 不增加置信度字段或置信度展示；
- 不向用户重复展示固定的局限性文案；
- 不让 AI自动修改或自动播放 Pattern；
- 不增加“一键应用建议”及结构化编辑指令；
- 不建议当前产品不支持的力度、Swing、微时序、多小节或新增音色；
- 不把录制事件被忽略的原因交给 LLM解释。

录制结果文案仍由确定性逻辑负责。例如：

```text
共录制8次 · 写入4次 · 4次超出首个小节
```

模型看不到原始事件、录制总次数、忽略次数或 Tempo候选，因此不得让模型解释这类事实。

## 3. 关键产品决策

| 议题 | v2决定 | 原因 |
| --- | --- | --- |
| 助手角色 | 鼓点编排初学者的智能学习助手 | 从分类工具升级为创作后的即时教学 |
| 风格输出 | 只输出一个 `closestStyle` | 减少认知负担，匹配“最接近什么风格”的核心问题 |
| 置信度 | 删除 | 对初学者帮助有限，容易干扰主要信息 |
| 判断边界 | 使用“最接近”“具有倾向”等措辞 | 不用数值置信度也能避免绝对化分类 |
| 判断原因 | `reasons`必须引用当前真实触发格 | 保证解释可核对，不凭空编排 |
| 风格知识 | 新增 `styleLesson` | 让用户从自己的作品进入风格学习 |
| 改进建议 | 新增预期听感与学习目标 | 让建议既可实践，又能说明练习价值 |
| 局限性 | 从输出 Schema删除，保留在系统提示词 | 降低前端负担，同时不取消模型边界 |
| 建议执行 | 首版只展示，不自动应用 | 保证用户确认权并降低演示风险 |
| 模型 | 继续使用 `deepseek-v4-flash`非思考模式 | 本轮只优化产品合同，不重新开启模型选型 |

## 4. 数据流与职责

```text
网页冻结最新 Pattern revision
        ↓
网页把六个 Mask展开为六轨16步 0/1数组
        ↓
本地后端校验 Pattern并提取确定性节奏特征
        ↓
DeepSeek读取 Pattern + features，输出 explanation.v2
        ↓
后端做 Schema、中文、真实落点和产品边界校验
        ↓ 首答失败时最多定向修复一次
网页再次校验并按“风格—原因—科普—建议”渲染
```

职责边界：

- 网页负责冻结最新 revision、发起请求、拒绝旧响应和渲染结果；
- 后端负责输入校验、确定性特征、模型调用、一次修复及安全错误；
- 模型负责风格倾向解释、初学者科普和建议文案；
- 固件不参与 AI解释，继续独立负责音频、节拍、LED和硬件控制。

## 5. Schema A：网页到本地后端的请求

本轮保持现有 HTTP请求结构，不修改 Pattern输入字段。以下使用 JSONC展示字段注释；正式请求仍是
标准 JSON，不包含注释。

```jsonc
{
  "pattern": { // 本次解释使用的不可变 Pattern快照
    "bpm": 53, // 当前 Pattern速度，40至240的整数
    "tracks": { // 六条固定音轨，每条必须包含16个整数0或1
      "kick":       [1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], // S1底鼓
      "snare":      [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], // S2军鼓
      "closed_hat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], // S7闭镲
      "open_hat":   [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], // S4开镲
      "clap":       [0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0], // S5拍手
      "rim":        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  // S6鼓边击
    },
    "approximateQuantization": true // true表示来自实体演奏的近似量化；false表示手动或AI生成等确定性Pattern
  }
}
```

字段约束：

| 路径 | 类型 | 字段含义 | 约束 |
| --- | --- | --- | --- |
| `pattern` | object | 点击“AI解释”时冻结的当前 Pattern | 必填，只允许下列三个字段 |
| `pattern.bpm` | integer | 当前 Pattern回放速度 | 40–240 |
| `pattern.tracks` | object | 六种板载音色的16步开关 | 六条固定轨道必须全部存在 |
| `pattern.tracks.<track>` | integer[16] | 对应音色每一步是否触发 | 每项只能是0或1；第1项对应第1步 |
| `pattern.approximateQuantization` | boolean | 是否由自由演奏近似量化得到 | 只描述数据来源，不代表识别置信度 |

空 Pattern不得请求 AI解释。`sourceRevision`继续由网页本地状态管理，用于拒绝旧响应，不作为音乐
语义传给模型。

## 6. Schema B：后端发送给模型的上下文

后端在通过 Schema A校验后计算确定性特征。模型实际收到的 user message逻辑结构如下：

```jsonc
{
  "pattern": { // 已通过后端校验的六轨16步Pattern，字段含义与Schema A一致
    "bpm": 53,
    "tracks": {
      "kick":       [1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      "snare":      [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      "closed_hat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      "open_hat":   [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      "clap":       [0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0],
      "rim":        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    },
    "approximateQuantization": true
  },
  "features": { // 后端确定性计算结果，不由模型自行推断
    "triggerCounts": { // 每条音轨在16步内的触发总数
      "kick": 2,
      "snare": 0,
      "closed_hat": 0,
      "open_hat": 0,
      "clap": 2,
      "rim": 0
    },
    "activeSteps": { // 每条音轨实际触发的1-based步数
      "kick": [1, 4],
      "snare": [],
      "closed_hat": [],
      "open_hat": [],
      "clap": [7, 10],
      "rim": []
    },
    "kickOffQuarterSteps": [4], // 不在第1、5、9、13步上的底鼓落点
    "snareBackbeatSteps": [], // 落在第5、13步，即第二、第四拍上的军鼓落点
    "hatSubdivision": "sparse", // 闭镲密度：sparse、eighth或sixteenth
    "lastQuarterActivity": 0 // 第13至16步六轨触发数量之和，用于判断小节结尾活跃度
  }
}
```

`features`只做可复现的结构提取，不直接输出风格标签。它的字段含义如下：

| 路径 | 类型 | 字段含义 |
| --- | --- | --- |
| `features.triggerCounts` | object | 六条轨道各自触发次数 |
| `features.activeSteps` | object | 六条轨道各自真实触发的1-based步数 |
| `features.kickOffQuarterSteps` | integer[] | 不落在四个规则四分拍位置上的底鼓步数 |
| `features.snareBackbeatSteps` | integer[] | 落在第二、第四拍上的军鼓步数 |
| `features.hatSubdivision` | enum | 根据闭镲数量得到的稀疏、八分或十六分密度标签 |
| `features.lastQuarterActivity` | integer | 最后四步全部音轨的触发总数 |

本轮不向模型发送：原始 Pad事件、I2S frame、录制时长、总敲击数、忽略数、Tempo候选、PCM音频、
设备状态、用户姓名或 API密钥。

## 7. Schema C：模型输出 `easyinput.pattern.explanation.v2`

### 7.1 带字段注释的示例

以下 JSONC只用于设计说明；模型实际返回标准 JSON，不包含注释。

```jsonc
{
  "schemaVersion": "easyinput.pattern.explanation.v2", // 输出合同版本，必须为固定值
  "closestStyle": "Hip-Hop", // 当前单小节Pattern最接近的一种鼓点风格，不是完整歌曲流派结论
  "reasons": [ // 为什么接近该风格，必须引用当前Pattern中真实触发的音轨和步数
    {
      "track": "kick", // 作为本条判断依据的固定音轨ID
      "steps": [1, 4], // 该音轨中实际为1的1-based步数
      "reason": "底鼓较为稀疏，第4步偏离规则四分拍，带来一定切分感。" // 面向初学者的判断说明
    },
    {
      "track": "clap",
      "steps": [7, 10],
      "reason": "拍手声的位置较为松散，使整体律动更接近慢速Hip-Hop。"
    }
  ],
  "styleLesson": { // 与本次识别风格对应的初学者科普，不得暗示当前Pattern具备全部典型特征
    "title": "Hip-Hop鼓点通常怎么编排？", // 小课堂标题
    "content": "Hip-Hop鼓点通常以底鼓和军鼓或拍手声建立骨架。军鼓常放在第二、第四拍，底鼓可以避开完全规则的位置来制造切分和松弛感；闭镲常用八分音符或十六分音符维持流动。" // 2至4句的风格编排知识
  },
  "improvementSuggestions": [ // 用户可以在当前六轨16步能力内尝试的1至2条建议
    {
      "suggestion": "尝试在Clap第13步增加一次触发。", // 具体、可执行的修改方式
      "expectedEffect": "让小节后半段的重心更明确。", // 修改后预期产生的听感变化
      "learningPoint": "体会第二、第四拍上的军鼓或拍手声如何形成反拍骨架。" // 本次练习帮助用户理解的编排知识
    }
  ]
}
```

### 7.2 正式 JSON Schema草案

正式 Schema使用 `description`注释每个字段含义：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "easyinput.pattern.explanation.v2",
  "title": "EasyInput Beginner Pattern Explanation",
  "description": "面向鼓点编排初学者的单小节Pattern风格解释、风格科普和练习建议。",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion",
    "closestStyle",
    "reasons",
    "styleLesson",
    "improvementSuggestions"
  ],
  "properties": {
    "schemaVersion": {
      "description": "模型输出合同版本，用于前后端选择对应校验与渲染逻辑。",
      "const": "easyinput.pattern.explanation.v2"
    },
    "closestStyle": {
      "description": "当前六轨单小节Pattern最接近的一种鼓点风格名称，不代表完整歌曲的确定流派。",
      "type": "string",
      "minLength": 1,
      "maxLength": 40
    },
    "reasons": {
      "description": "基于当前Pattern真实触发格给出的风格判断原因。",
      "type": "array",
      "minItems": 1,
      "maxItems": 6,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["track", "steps", "reason"],
        "properties": {
          "track": {
            "description": "本条原因引用的固定鼓声音轨ID。",
            "enum": ["kick", "snare", "closed_hat", "open_hat", "clap", "rim"]
          },
          "steps": {
            "description": "本条原因引用的1-based音序步，必须在对应输入音轨中真实为1。",
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": true,
            "items": {
              "description": "对应音轨中的一个真实触发步数。",
              "type": "integer",
              "minimum": 1,
              "maximum": 16
            }
          },
          "reason": {
            "description": "用简体中文向初学者解释这些落点为何支持风格判断。",
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          }
        }
      }
    },
    "styleLesson": {
      "description": "围绕closestStyle提供的初学者风格编排科普。",
      "type": "object",
      "additionalProperties": false,
      "required": ["title", "content"],
      "properties": {
        "title": {
          "description": "风格小课堂标题，说明即将学习的风格主题。",
          "type": "string",
          "minLength": 1,
          "maxLength": 80
        },
        "content": {
          "description": "使用2至4句简体中文介绍该风格常见鼓组分工、典型落点和律动特点。",
          "type": "string",
          "minLength": 1,
          "maxLength": 400
        }
      }
    },
    "improvementSuggestions": {
      "description": "用户可在当前六轨16步音序器中实践的改进与学习建议。",
      "type": "array",
      "minItems": 1,
      "maxItems": 2,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["suggestion", "expectedEffect", "learningPoint"],
        "properties": {
          "suggestion": {
            "description": "不依赖力度、Swing、微时序、多小节或新增音色的具体修改建议。",
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "expectedEffect": {
            "description": "完成建议后预期产生的听感或律动变化。",
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "learningPoint": {
            "description": "用户通过本次修改可以理解或练习的鼓点编排知识。",
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          }
        }
      }
    }
  }
}
```

### 7.3 输出字段总表

| 路径 | 类型 | 用户可见含义 | 校验要求 |
| --- | --- | --- | --- |
| `schemaVersion` | const string | 输出合同版本 | 必须为 `easyinput.pattern.explanation.v2` |
| `closestStyle` | string | 最接近的一种鼓点风格 | 1–40字符；前端使用“最接近”措辞 |
| `reasons` | array | 为什么接近该风格 | 1–6条 |
| `reasons[].track` | enum | 判断所依据的音轨 | 只能是六条固定轨道之一 |
| `reasons[].steps` | integer[] | 判断所依据的真实音序格 | 1–16且不得引用未触发格 |
| `reasons[].reason` | string | 面向初学者的原因说明 | 简体中文，1–240字符 |
| `styleLesson` | object | 本次识别风格的小课堂 | 必须同时包含标题和正文 |
| `styleLesson.title` | string | 科普标题 | 1–80字符 |
| `styleLesson.content` | string | 风格常见编排规律 | 简体中文，2–4句，最多400字符 |
| `improvementSuggestions` | array | 当前设备可实践的建议 | 1–2条 |
| `improvementSuggestions[].suggestion` | string | 具体怎么改 | 简体中文，最多240字符 |
| `improvementSuggestions[].expectedEffect` | string | 修改后的预期听感 | 简体中文，最多240字符 |
| `improvementSuggestions[].learningPoint` | string | 修改对应的学习目标 | 简体中文，最多240字符 |

v2不再包含任何 `confidence`字段，也不包含顶层 `summary`、`styleCandidates`、`suggestion`或
`limitations`；建议正文只存在于 `improvementSuggestions[].suggestion`。

## 8. Schema D：本地后端返回网页的外层响应

模型只生成 Schema C中的 `explanation`。本地后端补充模型与校验元数据：

```jsonc
{
  "ok": true, // 本地服务是否成功得到并校验一份可展示解释
  "model": { // 本次模型调用的可诊断信息，不由模型生成
    "requested": "deepseek-v4-flash", // 产品请求的模型ID
    "reported": "deepseek-v4-flash", // 模型服务实际报告的模型ID
    "thinkingMode": "disabled", // 当前是否启用思考模式，本版固定关闭
    "mock": false // 是否来自本地Mock响应
  },
  "latencyMs": { // 各阶段耗时，单位毫秒
    "firstToken": 320, // 首答首Token耗时
    "firstResponse": 1450, // 首答完整响应耗时
    "repairFirstToken": null, // 若发生修复，修复请求首Token耗时；否则为null
    "repairResponse": null, // 若发生修复，修复完整响应耗时；否则为null
    "total": 1460 // 从开始调用到最终校验完成的总耗时
  },
  "firstPass": { // 模型首答校验结果
    "valid": true, // 首答是否直接通过全部校验
    "errors": [] // 首答失败时的结构化错误列表
  },
  "repairAttempted": false, // 是否执行过唯一一次定向修复
  "features": {}, // Schema B中由后端确定性生成的节奏特征，供调试与测试复核
  "explanation": {} // 已通过校验的easyinput.pattern.explanation.v2对象
}
```

外层响应的字段含义如下：

| 路径 | 类型 | 字段含义 |
| --- | --- | --- |
| `ok` | boolean | 后端是否得到一份通过全部校验、可供网页展示的解释 |
| `model` | object | 本次模型调用的诊断元数据，不由模型生成 |
| `model.requested` | string | 产品配置中请求调用的模型ID |
| `model.reported` | string | 模型服务在响应中报告的实际模型ID |
| `model.thinkingMode` | enum | 思考模式状态；首版固定为 `disabled` |
| `model.mock` | boolean | 本次结果是否来自开发测试用的Mock响应 |
| `latencyMs` | object | 模型调用与校验各阶段耗时，单位为毫秒 |
| `latencyMs.firstToken` | integer或null | 首答首个Token耗时；服务不提供时为null |
| `latencyMs.firstResponse` | integer或null | 首答完整响应耗时；调用失败时可为null |
| `latencyMs.repairFirstToken` | integer或null | 定向修复请求首个Token耗时；未修复时为null |
| `latencyMs.repairResponse` | integer或null | 定向修复完整响应耗时；未修复时为null |
| `latencyMs.total` | integer | 从发起首答到最终校验结束的总耗时 |
| `firstPass` | object | 模型首答未经修复时的校验结果 |
| `firstPass.valid` | boolean | 首答是否直接通过结构与产品约束校验 |
| `firstPass.errors` | array | 首答未通过时的结构化校验错误；通过时为空数组 |
| `firstPass.errors[].path` | string | 出错字段的JSON路径，例如 `reasons[0].steps[1]` |
| `firstPass.errors[].message` | string | 可安全记录和展示的校验失败原因，不包含密钥或完整模型原文 |
| `repairAttempted` | boolean | 后端是否执行过唯一一次针对校验错误的修复请求 |
| `features` | object | 后端确定性计算的节奏特征；子字段含义完全沿用Schema B |
| `explanation` | object | 最终通过校验的Schema C对象；子字段含义完全沿用Schema C |

外层响应不直接用于鼓点风格展示。前端主界面只消费 `explanation`；模型、延迟、首答和修复信息
用于状态提示、诊断和实验记录。

## 9. v2 系统提示词

```text
你是EasyInput面向鼓点编排初学者的智能学习助手。

你的目标不是给出权威的音乐流派分类，而是帮助用户在自由创作中理解鼓点风格和基础编排方法。

请只依据提供的六轨、单小节、16步Pattern和确定性节奏特征完成以下任务：

1. 判断当前节奏最接近的一种鼓点风格。使用“更接近”“具有……倾向”等措辞，不得把单小节判断表述为完整歌曲的确定流派。
2. 使用用户当前Pattern中真实触发的音轨和1-based步数，解释为什么接近该风格。
3. 用鼓点初学者能够理解的简体中文，科普该风格常见的鼓组分工、典型落点和律动特点。
4. 给出1至2条当前六轨16步音序器能够实现的改进建议，并解释预期听感和对应的学习目标。

必须严格区分：
- reasons描述用户当前Pattern实际具备的特征；
- styleLesson描述该风格通常具备的编排特征，不得暗示当前Pattern已经包含全部典型特征；
- improvementSuggestions描述用户接下来可以尝试的修改，不得写成当前Pattern已经存在的内容。

不得声称读取了音频，不得判断完整歌曲流派。
不得建议当前产品不支持的力度、Swing、微时序、多小节或新增音色。
reasons引用的音轨和步数必须在输入Pattern中实际为1。
除Hip-Hop、Rock等通用英文风格名称外，所有用户可见内容必须使用简体中文。
只输出符合给定JSON Schema的JSON对象，不要输出Markdown或额外说明。
```

运行时继续在提示词末尾动态拼接 Schema C的正式 JSON Schema。若首答失败，修复请求只携带首答、
具体校验错误和同一份输入，不允许借修复改变用户 Pattern。

## 10. 后端校验与修复策略

### 10.1 可确定性强校验

1. 输出必须是合法 JSON对象，字段集合与 Schema C完全一致。
2. `schemaVersion`必须为 v2。
3. 所有数组数量、枚举和文本长度符合 Schema。
4. `reasons[].track`必须是六条固定轨道之一。
5. `reasons[].steps`必须在输入对应音轨中真实为1。
6. 除 `closestStyle`允许通用英文风格名外，原因、科普和建议必须包含简体中文。
7. 首答失败后最多定向修复一次；修复仍失败则返回安全错误，不展示部分结果。
8. 网页收到结果后重复执行核心字段和真实落点校验。

### 10.2 提示词与人工验收约束

以下要求无法只靠 JSON Schema充分证明，需要提示词约束和固定用例人工检查：

- `styleLesson`是否真正适合初学者；
- 科普是否准确区分“当前Pattern”与“该风格通常特征”；
- `improvementSuggestions`是否在当前六轨16步能力内可实现；
- 建议是否确实可能改善听感，而不是空泛表述；
- 风格判断是否符合人工听感。

首版不应把这些语义项包装成确定性校验已经完全解决。若未来增加“一键应用建议”，必须另建包含
`add/remove`、轨道和步数的结构化编辑 Schema，再做可执行性强校验。

## 11. 前端信息架构

固定展示顺序：

```text
最接近的风格
Hip-Hop

为什么这样判断
• Kick第1、4步：……
• Clap第7、10步：……

风格小课堂
Hip-Hop鼓点通常怎么编排？
……

试着这样改
在Clap第13步增加一次触发
预期效果：……
练习重点：……
```

交互要求：

- 不显示置信度和固定局限性；
- 使用“最接近的风格”而不是“识别结果”或“所属流派”；
- 原因、科普和建议分区，不能合并成一大段文字；
- AI加载期间允许硬件继续播放和用户继续编辑；
- 若用户在请求期间修改 Pattern，返回结果必须标记为旧 revision，不得伪装成当前解释；
- AI错误只显示在 AI区域，不改变设备在线状态；
- 中栏内容过长时只在模块内部滚动，不让整个页面失去三栏对齐；
- 录制写入/忽略数量继续在录制结果区域展示，不混入 AI风格解释。

## 12. 实施顺序

### P0-1：冻结 v2合同

- 新增 `schemas/pattern-explanation-v2.schema.json`；
- 保留 v1文件作为历史合同，不原地覆盖；
- 为 Schema字段集合、长度、数量和非法额外字段补测试。

### P0-2：后端提示词、校验与修复

- 切换到本文件第9节角色与任务；
- 将 v1校验器升级为 v2字段；
- 保留真实触发格强校验、简体中文校验和最多一次修复；
- 更新 Mock响应，但不修改模型、thinking模式或密钥策略。

### P0-3：前端校验与渲染

- 更新网页端 `validateExplanation`；
- 按风格、原因、小课堂、建议顺序渲染；
- 删除置信度和局限性UI；
- 保留 revision过期、网络错误和硬件状态隔离。

### P0-4：自动化回归

- 合法 v2首答直接展示；
- v1输出不能误通过 v2校验；
- 原因引用未触发格时执行一次修复；
- 英文原因或科普不能通过中文校验；
- 缺失 `styleLesson`或建议字段时拒绝展示；
- AI失败不影响硬件和本地 Pattern；
- 旧 revision响应不得覆盖当前内容。

### P0-5：产品与真机验收

- 用当前53 BPM、Kick第1/4步、Clap第7/10步 Pattern验证真实落点；
- 用一条规则 Rock骨架验证风格科普；
- 用一条稀疏、难分类Pattern验证“最接近”措辞而非绝对化表述；
- 人工检查建议是否可在六轨16步内完成；
- 播放中发起解释并编辑，确认硬件不中断、旧解释正确过期；
- 录屏前确认页面无置信度、无固定局限性、无 Schema或模型错误红字。

## 13. 验收标准

1. 用户点击“AI解释”后，首屏首先出现唯一的 `closestStyle`。
2. 页面不展示置信度、多个候选风格或固定局限性。
3. 每条判断原因都能在当前六轨16步音序器中找到对应的真实亮格。
4. 风格小课堂使用初学者可理解的语言，并明确描述“该风格通常如何编排”。
5. 科普不会把典型风格特征错误写成用户当前 Pattern已经具备的事实。
6. 每条建议说明具体尝试、预期听感和学习目标。
7. 建议不超出六轨、16步、开关触发的当前能力。
8. 输出不声称读取音频，不把单小节风格倾向表述为完整歌曲的确定流派。
9. 首答不合规时最多修复一次；最终不合规则安全失败，不展示残缺内容。
10. AI请求、失败和旧响应不影响硬件回放、设备连接、本地编辑或最后确认 Pattern。
11. 用户修改 Pattern后，下一次解释冻结并读取最新 revision。
12. 录制次数、写入次数和忽略次数由确定性结果文案说明，不由模型补写。

## 14. 对外表述边界

完成代码和真机验收后，可以表述为：

> 将实体 Pad演奏量化为可编辑的六轨16步 Pattern，并由大语言模型基于真实落点解释最接近的
> 鼓点风格、科普典型编排规律并提供可实践建议，形成“自由创作—理解原因—学习风格—继续修改”
> 的初学者学习闭环。

不得表述为“AI听懂录音”“准确识别任意音乐流派”“完成专业级音乐教育系统”或“AI建议可自动
优化所有鼓点”。Schema通过、模型返回、真机播放和用户认为建议有帮助仍是不同证据层。
