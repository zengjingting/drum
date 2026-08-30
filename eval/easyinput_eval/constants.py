from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = EVAL_ROOT / "schemas"
DATA_DIR = EVAL_ROOT / "data"
DEFAULT_RESULTS_ROOT = EVAL_ROOT / "results"

PATTERN_SCHEMA_PATH = SCHEMA_DIR / "pattern.schema.json"
REQUEST_SCHEMA_PATH = SCHEMA_DIR / "pattern-request.schema.json"
BENCHMARK_CASES_PATH = DATA_DIR / "benchmark-cases.json"

PATTERN_SCHEMA_VERSION = "easyinput.pattern.v1"
REQUEST_SCHEMA_VERSION = "easyinput.pattern-request.v1"
EXPERIMENT_VERSION = "easyinput-groove-eval.v1"

TRACK_IDS = (
    "kick",
    "snare",
    "closed_hat",
    "open_hat",
    "clap",
    "rim",
)
TRACK_ID_SET = frozenset(TRACK_IDS)

MIN_BPM = 40
MAX_BPM = 240
DEFAULT_BPM = 120
STEPS_PER_BAR = 16
BEAT_STEPS = (1, 5, 9, 13)

SUPPORTED_CONSTRAINT_TYPES = frozenset(
    {
        "bpm_equals",
        "track_exact_steps",
        "track_steps_on",
        "track_steps_value",
        "track_count_range",
        "track_has_trigger_outside",
        "track_count_less_than_current",
        "tracks_count_range_in_steps",
        "track_count_range_in_steps",
    }
)
