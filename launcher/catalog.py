"""Setting definitions for llama-server, with validation and argv emission.

Pinned to llama.cpp build 10453 (commit 3cb7ffb1a). If the binary is rebuilt and
its allowed values change, update CACHE_TYPES / SPEC_TYPES below.
"""
import copy
import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Optional

CACHE_TYPES = ["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]
SPEC_TYPES = ["none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash",
              "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v",
              "ngram-mod", "ngram-cache"]
ONOFFAUTO = ["on", "off", "auto"]

# Passed through to the chat template, which decides what it honours - llama-server
# itself accepts any string here. These are the levels build 10453 documents.
REASONING_EFFORTS = ["default", "minimal", "low", "medium", "high", "xhigh", "max"]

# Spec types needing a separate draft-model GGUF. draft-mtp is deliberately absent:
# the multi-token-prediction head is built into the model's own weights.
DRAFT_MODEL_TYPES = {"draft-simple", "draft-eagle3", "draft-dflash", "draft-dspark"}


@dataclass
class Setting:
    key: str
    flag: str
    label: str
    type: str                      # int float str path choice tri bool json raw
    default: Any = None
    choices: Optional[list] = None
    lo: Optional[float] = None
    hi: Optional[float] = None


@dataclass
class Group:
    key: str
    label: str
    settings: list = field(default_factory=list)


GROUPS = [
    Group("context", "context", [
        Setting("context", "-c", "context", "int", 8192, lo=1),
    ]),
    Group("gpu", "gpu layers", [
        Setting("gpu_layers", "-ngl", "gpu layers", "gpu_layers", "auto"),
    ]),
    Group("net", "host:port", [
        Setting("host", "--host", "host", "str", "127.0.0.1"),
        Setting("port", "--port", "port", "int", 8080, lo=1, hi=65535),
    ]),
    Group("sampling", "sampling", [
        Setting("temp", "--temp", "temp", "float", 0.6, lo=0),
        Setting("top_k", "--top-k", "top-k", "int", 20, lo=0),
        Setting("top_p", "--top-p", "top-p", "float", 0.95, lo=0, hi=1),
        Setting("min_p", "--min-p", "min-p", "float", 0.0, lo=0, hi=1),
    ]),
    # Their own row rather than four more fields on sampling: eight values on one
    # line stops being readable, and these four are one concept.
    Group("penalties", "penalties", [
        Setting("presence_penalty", "--presence-penalty", "presence", "float", 0.0),
        Setting("frequency_penalty", "--frequency-penalty", "frequency", "float", 0.0),
        # 1.0 disables. Not 0.0 - this one is a multiplier, unlike its neighbours.
        Setting("repeat_penalty", "--repeat-penalty", "repeat", "float", 1.0, lo=0),
        # lo=0 because 0 disables and the binary REJECTS -1, unlike some older
        # llama.cpp builds where -1 meant "the whole context".
        Setting("repeat_last_n", "--repeat-last-n", "repeat-last-n", "int", 64, lo=0),
    ]),
    Group("toggles", "toggles", [
        Setting("jinja", "--jinja", "jinja", "bool", True),
        Setting("no_mmproj", "--no-mmproj", "no-mmproj", "bool", True),
        Setting("reasoning", "--reasoning", "reasoning", "choice", "auto", ONOFFAUTO),
        Setting("reasoning_effort", "--reasoning-effort", "effort", "choice",
                "default", REASONING_EFFORTS),
        Setting("reasoning_preserve", "--reasoning-preserve", "reason-preserve", "tri", None),
        Setting("metrics", "--metrics", "metrics", "bool", False),
        Setting("flash_attn", "--flash-attn", "fa", "choice", "on", ONOFFAUTO),
        Setting("kv_unified", "--kv-unified", "kv-unified", "tri", None),
    ]),
    Group("kv", "kv cache", [
        Setting("cache_type_k", "-ctk", "K", "choice", "f16", CACHE_TYPES),
        Setting("cache_type_v", "-ctv", "V", "choice", "f16", CACHE_TYPES),
    ]),
    Group("batching", "batching", [
        Setting("parallel", "-np", "-np", "int", -1),
        Setting("batch", "-b", "-b", "int", 2048, lo=1),
        Setting("ubatch", "-ub", "-ub", "int", 512, lo=1),
    ]),
    Group("spec", "speculative", [
        Setting("spec_type", "--spec-type", "spec-type", "spec_type", "none"),
        Setting("draft_model", "--spec-draft-model", "draft model", "path", None),
        Setting("spec_ngl", "--spec-draft-ngl", "draft ngl", "gpu_layers", "auto"),
        Setting("spec_n_max", "--spec-draft-n-max", "n-max", "int", 3, lo=0),
        Setting("spec_n_min", "--spec-draft-n-min", "n-min", "int", 0, lo=0),
        Setting("spec_p_min", "--spec-draft-p-min", "p-min", "float", 0.0, lo=0, hi=1),
    ]),
    Group("template", "template", [
        Setting("chat_template_kwargs", "--chat-template-kwargs", "kwargs", "json", {}),
    ]),
    Group("extra", "extra args", [
        Setting("extra", "", "extra", "raw", ""),
    ]),
]


def settings_by_key():
    return {s.key: s for g in GROUPS for s in g.settings}


def catalog_defaults():
    return copy.deepcopy({s.key: s.default for g in GROUPS for s in g.settings})


def _range_error(setting, value):
    """Bounds message, or None if the value is in range.

    ASCII ONLY. This machine's console is cp1252; printing a non-ASCII character
    raises UnicodeEncodeError and kills the launcher. An unbounded side is worded
    rather than symbolised for exactly that reason."""
    lo, hi = setting.lo, setting.hi
    if lo is not None and value < lo:
        return f"must be between {lo} and {hi}" if hi is not None else f"must be at least {lo}"
    if hi is not None and value > hi:
        return f"must be between {lo} and {hi}" if lo is not None else f"must be at most {hi}"
    return None


def parse_value(setting, text):
    """Parse user input for one setting. Returns (True, value) or (False, error)."""
    text = (text or "").strip()
    t = setting.type

    if t == "tri":
        if text == "":
            return True, None
        if text in ("on", "off"):
            return True, text
        return False, "enter 'on', 'off', or blank to leave unset"

    if t == "bool":
        if text.lower() in ("y", "yes", "true", "on", "1"):
            return True, True
        if text.lower() in ("n", "no", "false", "off", "0"):
            return True, False
        return False, "enter y or n"

    if t == "int":
        try:
            value = int(text)
        except ValueError:
            return False, "enter a whole number"
        err = _range_error(setting, value)
        return (False, err) if err else (True, value)

    if t == "float":
        try:
            value = float(text)
        except ValueError:
            return False, "enter a number"
        err = _range_error(setting, value)
        return (False, err) if err else (True, value)

    if t == "choice":
        if text in setting.choices:
            return True, text
        return False, "allowed: " + ", ".join(setting.choices)

    if t == "gpu_layers":
        if text in ("auto", "all"):
            return True, text
        if text.isdigit():
            return True, text
        return False, "enter 'auto', 'all', or a layer count"

    if t == "spec_type":
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts:
            return True, "none"
        for p in parts:
            if p not in SPEC_TYPES:
                return False, f"unknown spec type {p!r}; allowed: " + ", ".join(SPEC_TYPES)
        return True, ",".join(parts)

    if t == "json":
        if text == "":
            return True, {}
        try:
            value = json.loads(text)
        except ValueError as exc:
            return False, f"invalid JSON: {exc}"
        if not isinstance(value, dict):
            return False, "must be a JSON object, e.g. {\"key\": true}"
        return True, value

    if t == "raw":
        try:
            shlex.split(text)
        except ValueError as exc:
            return False, f"unbalanced quoting: {exc}"
        return True, text

    return True, text            # str, path


def _negate(flag):
    """--kv-unified -> --no-kv-unified"""
    return "--no-" + flag.lstrip("-")


def emit(setting, value):
    """Render one setting as argv fragments. Empty list means 'omit entirely'."""
    if value is None:
        return []
    t = setting.type

    if t == "bool":
        return [setting.flag] if value else []

    if t == "tri":
        if value == "on":
            return [setting.flag]
        if value == "off":
            return [_negate(setting.flag)]
        return []

    if t == "json":
        if not value:
            return []
        return [setting.flag, json.dumps(value, separators=(",", ":"))]

    if t == "raw":
        return shlex.split(value) if value else []

    return [setting.flag, str(value)]


def spec_types_of(values):
    raw = values.get("spec_type") or "none"
    return [p.strip() for p in raw.split(",") if p.strip()]


def spec_error(values):
    """Validate the speculative group before launch. None means OK."""
    types = spec_types_of(values)
    if types == ["none"] or not types:
        return None
    needs_draft = [t for t in types if t in DRAFT_MODEL_TYPES]
    has_draft = bool(values.get("draft_model"))
    if needs_draft and not has_draft:
        return (f"spec-type {needs_draft[0]!r} needs a draft model "
                f"- set one on the speculative row")
    if "draft-mtp" in types and has_draft:
        return ("spec-type 'draft-mtp' takes no draft model - MTP is built into "
                "the model's own weights; clear the draft model row")
    return None


def active_keys(values):
    """Which setting keys emit, given the current values. Encodes the gating."""
    keys = {s.key for g in GROUPS for s in g.settings}
    types = spec_types_of(values)

    if types == ["none"] or not types:
        return keys - {"spec_type", "draft_model", "spec_ngl",
                       "spec_n_max", "spec_n_min", "spec_p_min"}

    if not any(t in DRAFT_MODEL_TYPES for t in types):
        # draft-mtp and every ngram-* type run without a separate draft GGUF
        keys -= {"draft_model", "spec_ngl"}
    return keys


def editable_keys(values):
    """Which setting keys the board prompts for. Same gating as emission, except
    spec_type is always editable - otherwise row 8 could never be switched on,
    since 'none' is the default and 'none' removes itself from active_keys."""
    return active_keys(values) | {"spec_type"}


def build_argv(values, model_path, alias, draft_path=None):
    """Full argv after the executable. Caller prepends the llama-server path."""
    argv = ["--model", model_path, "--alias", alias]
    live = active_keys(values)

    for group in GROUPS:
        for setting in group.settings:
            if setting.key not in live:
                continue
            if setting.key == "draft_model":
                if draft_path:
                    argv += [setting.flag, draft_path]
                continue
            argv += emit(setting, values.get(setting.key))
    return argv
