"""Setting definitions for llama-server, with validation and argv emission.

Pinned to llama.cpp build 10453 (commit 3cb7ffb1a). If the binary is rebuilt and
its allowed values change, update CACHE_TYPES / SPEC_TYPES below.
"""
import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Optional

CACHE_TYPES = ["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]
SPEC_TYPES = ["none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash",
              "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v",
              "ngram-mod", "ngram-cache"]
ONOFFAUTO = ["on", "off", "auto"]

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
        Setting("presence_penalty", "--presence-penalty", "presence", "float", 0.0),
    ]),
    Group("toggles", "toggles", [
        Setting("jinja", "--jinja", "jinja", "bool", True),
        Setting("no_mmproj", "--no-mmproj", "no-mmproj", "bool", True),
        Setting("reasoning", "--reasoning", "reasoning", "choice", "auto", ONOFFAUTO),
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
    return {s.key: s.default for g in GROUPS for s in g.settings}


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
        if setting.lo is not None and value < setting.lo:
            hi = setting.hi if setting.hi is not None else "∞"
            return False, f"must be between {setting.lo} and {hi}"
        if setting.hi is not None and value > setting.hi:
            return False, f"must be between {setting.lo} and {setting.hi}"
        return True, value

    if t == "float":
        try:
            value = float(text)
        except ValueError:
            return False, "enter a number"
        if setting.lo is not None and value < setting.lo:
            return False, f"must be between {setting.lo} and {setting.hi}"
        if setting.hi is not None and value > setting.hi:
            return False, f"must be between {setting.lo} and {setting.hi}"
        return True, value

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
