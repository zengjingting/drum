# EasyInput AI Pattern Evaluation Harness

This directory implements the machine-readable portion of
[`docs/ai-pattern-model-evaluation-plan.md`](../docs/ai-pattern-model-evaluation-plan.md).
It never sends `PATTERN` to hardware. A valid model result only produces six masks and leaves
`hardwareAck` as `null` for a later, explicit hardware test.

## Safety and run modes

- Running the CLI with no subcommand only prints help and makes no model call.
- `smoke` runs one non-scoring case and defaults to local Ollama only.
- `warmup` records are created only as a separate prelude to a formal run.
- `formal` is blocked unless all three providers are ready, experiment artifact identifiers are
  supplied, and the exact confirmation phrase is passed.
- JSONL files are physically separated under `results/smoke`, `results/warmup`, and
  `results/formal`. A record store rejects a mismatched `runMode`.

A formal experiment contains 18 scored first responses (6 cases x 3 providers), preceded by 3
unscored warmup requests. Each scored response may trigger at most one repair request, so the
maximum transport-call count is 39 rather than 18. The confirmation phrase names 18 cases, not
18 API calls: `RUN_18_CASES_WITH_UP_TO_ONE_REPAIR_EACH`.

## Contract check and tests

```bash
python3 -m eval.easyinput_eval.cli inspect
python3 -m unittest discover -s eval/tests -v
```

## Provider readiness

```bash
python3 -m eval.easyinput_eval.cli providers
```

Cloud providers are marked `available: false` when `ZHIPUAI_API_KEY` or
`DEEPSEEK_API_KEY` is absent. Missing credentials are never treated as a successful result.
The frozen provider requests are `qwen3.5:2b`, `glm-5.3-flash`, and
`deepseek-v4-flash`. DeepSeek records the official documented version
`DeepSeek-V4-Flash-0731` separately from `responseReportedModel`. The Chat Completions response
currently reports only the request alias, so `modelVersionEvidence` records that fact instead of
claiming a false version mismatch.

Keep credentials out of source files and shell history. In zsh, load newly rotated keys into the
current terminal with hidden input, then run the readiness check in that same terminal:

```zsh
read -s "ZHIPUAI_API_KEY?Zhipu API key: "; echo; export ZHIPUAI_API_KEY
read -s "DEEPSEEK_API_KEY?DeepSeek API key: "; echo; export DEEPSEEK_API_KEY
python3 -m eval.easyinput_eval.cli providers
```

The provider thinking settings are intentionally recorded rather than normalized falsely:

- Ollama Qwen and DeepSeek request thinking disabled.
- `glm-5.3-flash` only supports enabled thinking, so the adapter requests
  `reasoning_effort=low` and records `thinkingMode=enabled_low`.

## One local, non-scoring smoke call

```bash
python3 -m eval.easyinput_eval.cli smoke --provider ollama --case G-HOUSE
```

By default a smoke call does not attempt a repair. Add `--allow-repair` only when testing the
one-repair path. The formal command is intentionally not shown as a copy-paste quick start; use
`python3 -m eval.easyinput_eval.cli formal --help` after the experiment inputs and hardware
artifacts are frozen.

## Result semantics

Each record keeps these outcomes separate:

- `firstPassSchemaValid`: strict JSON and six-track/16-step output contract;
- `firstPassConstraintsValid`: case-specific musical/instruction rules;
- `firstPassEditPolicyValid`: immutable edit fields/cells;
- `maskConversionValid`: successful, deterministic 16-step-to-uint16 conversion.
- `hardwareEligible`: schema, case constraints, edit policy, and mask conversion all passed.

A schema-valid result that violates House four-on-the-floor can still prove deterministic mask
conversion, but remains a constraint failure and has `hardwareEligible=false`. If a repair is
allowed, first-pass evidence remains unchanged and repair evidence is written into separate
fields.

## Auditable score summary

`summarize_records(records, hardware_acks=None)` in `easyinput_eval.scoring` is a pure function:
it does not read result files, write reports, or mutate records. Pass the 18 formal JSONL records
as dictionaries. The optional hardware argument accepts either a `runId -> ACK` mapping or the
hardware evidence artifact containing a `results` array.

The function keeps the pre-registered denominators fixed: six cases for structure, 15 explicit
constraint results plus three first-pass edit-policy checks for instruction following. Missing
ACKs score zero and remain marked as unverified; blind listening and the 100-point total stay
`null`. Hardware ACK evidence does not prove the flashed firmware commit. If the evidence artifact
states that `STATE` could not verify the commit, the summary preserves that as an `auditGaps`
entry rather than treating the intended source commit as device proof.
