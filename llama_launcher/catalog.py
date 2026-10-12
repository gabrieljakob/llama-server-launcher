"""Setting definitions for llama-server, with validation and argv emission.

Pinned to llama.cpp build 10453 (commit 3cb7ffb1a). If the binary is rebuilt and
its allowed values change, update CACHE_TYPES / SPEC_TYPES below.
"""
import copy
import json
import math
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

# Spec types that CANNOT launch without a separate draft-model GGUF.
DRAFT_MODEL_TYPES = {"draft-simple", "draft-eagle3", "draft-dflash", "draft-dspark"}

# Spec types that TAKE a draft model but do not require one. draft-mtp normally
# needs a draft GGUF like any other draft-* type; it goes without only when the
# multi-token-prediction head is built into the model's own weights, and that is
# a property of the weights, not of the type. The launcher cannot tell the two
# apart by reading the string, so it offers the row and demands nothing - the
# previous split had no such tier, treated every draft-mtp config as head-in-
# weights, and made the ordinary case impossible to express: the board hid the
# row, active_keys dropped the key, and edit_group deleted a hand-edited path.
DRAFT_MODEL_OPTIONAL_TYPES = {"draft-mtp"}


def _takes_draft_model(types):
    """True when any of these types can carry a separate draft GGUF at all,
    required or optional. Gating asks this; only spec_error asks the stricter
    'must have one' question, off DRAFT_MODEL_TYPES alone."""
    return any(t in DRAFT_MODEL_TYPES or t in DRAFT_MODEL_OPTIONAL_TYPES
               for t in types)


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
    #
    # All four default to None, meaning "we do not pass this flag; llama-server
    # uses its own default". That is deliberate. Pre-filling them with the
    # server's defaults (0.0 / 0.0 / 1.0 / 64) would put numbers on the board
    # that nobody chose, and a user who does not know these samplers cannot tell
    # a default apart from a decision. Worse, the pairing is not even uniform -
    # 0.0 disables presence and frequency, but 1.0 is what disables repeat - so
    # the pre-filled row would actively mislead. Unset renders as "-" and emits
    # nothing; a value appears only once someone sets one.
    Group("penalties", "penalties", [
        Setting("presence_penalty", "--presence-penalty", "presence", "float", None),
        Setting("frequency_penalty", "--frequency-penalty", "frequency", "float", None),
        Setting("repeat_penalty", "--repeat-penalty", "repeat", "float", None, lo=0),
        # lo=0 because 0 disables and the binary REJECTS -1, unlike some older
        # llama.cpp builds where -1 meant "the whole context".
        Setting("repeat_last_n", "--repeat-last-n", "repeat-last-n", "int", None, lo=0),
    ]),
    # Their own row rather than four more fields on toggles, for the reason the
    # penalties row exists: eight values on one line stops being readable, and
    # these four are one concept. It is also the row a model's own startup log
    # sends people to - build 10453 announces a template with the
    # 'supports_preserve_reasoning' capability - and a lever nobody can find on
    # the board is a lever nobody uses. `preserve` and `budget` are BOTH unset
    # by default: llama-server's answer is the template's own default and -1
    # (unrestricted), and neither is ours to assume.
    Group("reasoning", "reasoning", [
        Setting("reasoning", "--reasoning", "reasoning", "choice", "auto", ONOFFAUTO),
        Setting("reasoning_effort", "--reasoning-effort", "effort", "choice",
                "default", REASONING_EFFORTS),
        Setting("reasoning_preserve", "--reasoning-preserve", "preserve", "tri", None),
        # lo=-1 and not lo=0: -1 is unrestricted, 0 ends thinking immediately,
        # N>0 is a token budget - so -1 is the smallest value the flag has a
        # meaning for. Build 10453 accepts -2 without a word, which leaves a
        # typo to be discovered as strange model behaviour rather than as a
        # message on the row it came from.
        Setting("reasoning_budget", "--reasoning-budget", "budget", "int", None,
                lo=-1),
        # Only ever read when a budget runs out, and it travels with the budget
        # for that reason. Unvalidated free text: it is injected into the model's
        # own thinking, just before the end-of-thinking tag, so its content is a
        # prompt-writing decision and not the launcher's business. It emits as
        # ONE argv entry, spaces and all - spawn() passes a list, and [c] quotes
        # it for PowerShell.
        Setting("reasoning_budget_message", "--reasoning-budget-message",
                "budget-message", "str", None),
    ]),
    Group("toggles", "toggles", [
        Setting("jinja", "--jinja", "jinja", "bool", True),
        Setting("no_mmproj", "--no-mmproj", "no-mmproj", "bool", True),
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
    # deepcopy, not a plain dict comprehension: at least one default is mutable
    # (chat_template_kwargs is {}). Handing every caller the same object means one
    # caller mutating it in place poisons the default for the whole process, and
    # every config created afterwards silently inherits the change.
    return {s.key: copy.deepcopy(s.default) for g in GROUPS for s in g.settings}


def split_extra(text):
    """Split the extra-args row using WINDOWS rules, not POSIX.

    shlex.split is POSIX: it treats backslash as an escape, so
        --lora D:\\LLM Models\\adapters\\x.gguf
    became ['--lora', 'D:LLM', 'Modelsadaptersx.gguf'] - silently corrupted and
    handed to a real server. Every path on this machine has backslashes, and
    extra-args exists precisely for path-bearing flags like --chat-template-file
    and --lora, so POSIX rules were wrong for this field in every realistic use.

    Windows rules: backslash is an ordinary character, only " groups, and a
    doubled "" inside a quoted run is a literal quote. Unbalanced quotes are
    reported rather than raised - this text comes from a config file that may
    have been hand-edited.

    Returns (True, [args]) or (False, error)."""
    args, cur, in_quotes, started = [], [], False, False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            if in_quotes and i + 1 < len(text) and text[i + 1] == '"':
                cur.append('"')          # "" inside quotes is a literal quote
                i += 2
                continue
            in_quotes = not in_quotes
            started = True
        elif c.isspace() and not in_quotes:
            if started or cur:
                args.append("".join(cur))
                cur, started = [], False
        else:
            cur.append(c)
            started = True
        i += 1
    if in_quotes:
        return False, 'unbalanced quote - every " needs a closing one'
    if started or cur:
        args.append("".join(cur))
    return True, args


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

    # A setting whose catalog default is None means "we do not pass this flag".
    # "-" puts it back there. Without an explicit way to unset, a value could be
    # set once and never cleared - the same dead end that stranded draft_model,
    # where the launcher refused to start and named a row the UI would not offer.
    if text == "-" and setting.default is None and t not in ("tri", "bool"):
        return True, None

    if t == "tri":
        # "-" unsets, NOT blank. Blank means "keep what is there" for every
        # other type, and the prompt shows the current value in brackets, so
        # making blank destructive here silently erased a saved setting the
        # moment anyone pressed Enter through this row. One convention, no
        # exceptions: blank keeps, "-" clears.
        if text == "-":
            return True, None
        if text in ("on", "off"):
            return True, text
        return False, "enter 'on', 'off', or '-' to leave it to llama-server"

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
        # nan defeats every bound: nan < lo and nan > hi are BOTH False, so a
        # nan sails past _range_error into the config file - where json.dump
        # writes a bare NaN, which is not valid JSON and no strict parser will
        # read back. inf slips through any bound that has no upper limit.
        if not math.isfinite(value):
            return False, "enter a finite number"
        err = _range_error(setting, value)
        return (False, err) if err else (True, value)

    if t == "choice":
        if text in setting.choices:
            return True, text
        return False, "allowed: " + ", ".join(setting.choices)

    if t == "gpu_layers":
        if text in ("auto", "all"):
            return True, text
        # ASCII decimal digits, and isdigit() alone is NOT that test. This value
        # is stored AS TEXT and emit() sends the text - unlike the int type,
        # where int() normalises the digits and str() writes them back as ASCII,
        # nothing rewrites this one on the way out. So superscript two (isdigit,
        # and int() refuses it), Arabic-Indic three and the fullwidth digits
        # (isdigit AND isdecimal, and int() reads them fine) all used to be
        # accepted here and then handed to llama-server verbatim, which answers
        #     error while handling argument "-ngl": invalid stoi argument
        # and EXITS 0 - so wait_ready reports "exited with code 0 before the
        # port opened" and names nothing the user could act on.
        #
        # board.dispatch can afford isdecimal() because it converts with int()
        # and uses the int. Here the characters themselves are the argument, so
        # isascii() is what keeps the stored value and the -ngl argument the
        # same string.
        if text.isascii() and text.isdigit():
            return True, text
        return False, "enter 'auto', 'all', or a layer count"

    if t == "spec_type":
        parts = _spec_parts(text)
        if not parts:
            return True, "none"
        for p in parts:
            if p not in SPEC_TYPES:
                return False, f"unknown spec type {p!r}; allowed: " + ", ".join(SPEC_TYPES)
        # 'none' means no speculative decoding AT ALL: it is the whole list, or
        # the list is wrong. BOTH bad shapes used to be accepted here.
        # "none,draft-mtp" is a contradiction build 10453 does not diagnose - it
        # takes the token without a word, leaving the user to guess which half
        # won. "none,none" was worse: it passed straight through to spec_error,
        # which indexed an empty 'others' list and took the launcher down with an
        # IndexError, from the speculative row, on Enter.
        if "none" in parts and len(parts) > 1:
            others = [p for p in parts if p != "none"]
            if others:
                return False, (f"'none' cannot be combined with {others[0]!r} - "
                               f"'none' means no speculative decoding at all. "
                               f"Drop one of them.")
            return False, (f"'none' is listed {len(parts)} times - 'none' means "
                           f"no speculative decoding at all; write it once, "
                           f"on its own.")
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
        # "-" clears the row, exactly as it does on the penalties rows. The
        # generic unset branch above cannot cover this one, because the catalog
        # default here is "" rather than None - so "-" used to be stored as a
        # LITERAL "-", emitted as a bare argument, and rejected by the binary.
        # Blank keeps the current value for every type, so without this there
        # was no way back to an empty extra-args row at all. "" and not None:
        # the board renders a raw value only when it is a string, and the empty
        # string is what emit() already treats as "send nothing".
        if text == "-":
            return True, ""
        ok, result = split_extra(text)
        return (True, text) if ok else (False, result)

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
        # isinstance, not just truthiness: a hand-edited config can put a string
        # or a list here, and json.dumps would happily serialise either into a
        # --chat-template-kwargs llama-server rejects. Dropping it keeps the
        # launch usable; the board still shows the bad value so it can be fixed.
        if not isinstance(value, dict) or not value:
            return []
        return [setting.flag, json.dumps(value, separators=(",", ":"))]

    if t == "raw":
        if not value:
            return []
        if not isinstance(value, str):
            return []            # a number here is not an argument list
        ok, args = split_extra(value)
        # Unbalanced quoting is rejected at edit time; a hand-edited config can
        # still carry it, and dropping the row beats raising mid-launch.
        return args if ok else []

    if t == "spec_type":
        # NORMALISED, not raw. parse_value and spec_error both judge the split
        # form, so emitting the stored text verbatim sent something neither of
        # them ever saw: a hand-edited "ngram-mod, ngram-cache" (one space)
        # passes every check here and then reaches build 10453 as
        # "unknown speculative type:  ngram-cache" - the leading space is part
        # of the type name by the time the binary splits it. What was validated
        # is what gets sent.
        parts = _spec_parts(value)
        return [setting.flag, ",".join(parts)] if parts else []

    return [setting.flag, str(value)]


def _spec_parts(raw):
    """Split one raw --spec-type value into its members, whitespace stripped.

    str(): everything downstream - the board, active_keys, emit, build_argv -
    goes through here, and a hand-edited config can hold a number or a list on
    this key. Coercing once, in one place, is what keeps all of them total;
    raising would take the board down before the user could reach the row to
    fix it."""
    if not isinstance(raw, str):
        raw = str(raw)
    return [p.strip() for p in raw.split(",") if p.strip()]


def spec_types_of(values):
    """The spec types as a list of strings."""
    return _spec_parts(values.get("spec_type") or "none")


def _spec_off(types):
    """True when this list means 'no speculative decoding'.

    Every member 'none', not just the single-element list: "none,none" is
    refused before launch, but until the user fixes it the board still renders
    and build_argv still runs, and a config that says nothing but 'none' must
    not emit --spec-* flags on the way through."""
    return not types or all(t == "none" for t in types)


def draft_model_set(values):
    """True when draft_model actually names something.

    Blank after strip is ABSENT, not a path. '   ' is truthy in Python, so it
    satisfied every `if values.get("draft_model")` in the launcher: spec_error
    accepted it as the draft model a draft-* type requires, and the launch then
    resolved it into the model root plus three spaces and said only "draft model
    is gone". Whitespace is not a path anyone typed on purpose - it is an empty
    row with a stray space in it, and it must be refused where the message can
    still name the row."""
    draft = values.get("draft_model")
    return isinstance(draft, str) and bool(draft.strip())


def spec_carries_own_head(values):
    """True when the current spec type is RECOGNISED and genuinely runs without
    a separate draft GGUF - draft-mtp and the ngram-* family.

    Deliberately not the same question as `"draft_model" not in active_keys`.
    active_keys drops draft_model for anything that is not a known draft-* type,
    which includes a type it has never heard of: a hand-edited "ngram-modd"
    dropped the key exactly as "ngram-mod" does. Any caller that read that as
    "this model carries its own prediction head" was believing something about a
    string the catalog cannot interpret at all.

    'none' is False as well. It does not carry its own head, it means no
    speculative decoding, and "none,ngram-mod" is a contradiction spec_error
    refuses - neither is a state to draw conclusions about the model from."""
    types = spec_types_of(values)
    if not types or any(t not in SPEC_TYPES for t in types):
        return False
    if "none" in types:
        return False
    return not _takes_draft_model(types)


def spec_error(values):
    """Validate the speculative group before launch. None means OK.

    TOTAL: it returns a string or None for ANY values dict, whatever JSON types
    a hand edit put on these keys. It gates both [Enter] and [c], so raising
    here takes down the only screen the value could be repaired from."""
    types = spec_types_of(values)

    # Checked first, and regardless of the spec type, because this one is not
    # merely invalid - it is a TypeError in the caller. Both launch and [c] do
    #     config.resolve_path(values["draft_model"], root)
    # whenever the value is truthy, and os.path.isabs(7) raises. Refusing here
    # is what turns a traceback out of a hand-edited number into a message.
    draft = values.get("draft_model")
    if draft is not None and not isinstance(draft, str):
        return (f"draft model must be a path, not a {type(draft).__name__} "
                f"({draft!r}) - fix or clear it on the speculative row")

    # 'none' means no speculative decoding AT ALL, so it cannot be one member of
    # a list - "none,draft-mtp" is a contradiction. Checked here because build
    # 10453 does NOT check it: verified with --model nonexistent.gguf, the
    # binary accepts "none,draft-mtp" without a word, so the user is left
    # guessing which half of their contradiction won. Refusing is the only way
    # they find out they wrote one.
    if "none" in types and len(types) > 1:
        others = [t for t in types if t != "none"]
        # `others` is EMPTY for "none,none". Indexing it unguarded is what made
        # this function raise IndexError instead of returning a message.
        if others:
            return (f"spec-type cannot combine 'none' with {others[0]!r} - 'none' "
                    f"means no speculative decoding at all. Drop one of them.")
        return (f"spec-type lists 'none' {len(types)} times - 'none' means no "
                f"speculative decoding at all; write it once, on its own.")
    unknown = [t for t in types if t not in SPEC_TYPES]
    if unknown:
        # parse_value rejects these at edit time; only a hand-edited config gets
        # here. Verified against build 10453: the binary refuses an unknown type
        # with "unknown speculative type: 3" - and then EXITS 0, so wait_ready
        # reports "exited with code 0 before the port opened" and names nothing.
        return (f"unknown spec-type {unknown[0]!r} on the speculative row; "
                f"allowed: " + ", ".join(SPEC_TYPES))
    if _spec_off(types):
        return None
    needs_draft = [t for t in types if t in DRAFT_MODEL_TYPES]
    if needs_draft and not draft_model_set(values):
        return (f"spec-type {needs_draft[0]!r} needs a draft model "
                f"- set one on the speculative row")
    # A draft model left over from a previous spec type is NOT refused. For
    # draft-mtp and every ngram-* type active_keys already drops draft_model, so
    # the flag provably cannot reach llama-server - the command line is already
    # correct, and refusing it blocked a launch that had nothing wrong with it.
    # The old message ("clear the draft model row") named a row the board hides
    # for exactly these types: an instruction the UI cannot obey, which is a
    # dead end for a hand-edited config. edit_group clears the stale value, and
    # says so, the next time the speculative row is opened.
    return None


def active_keys(values):
    """Which setting keys emit, given the current values. Encodes the gating."""
    keys = {s.key for g in GROUPS for s in g.settings}
    types = spec_types_of(values)

    if _spec_off(types):
        return keys - {"spec_type", "draft_model", "spec_ngl",
                       "spec_n_max", "spec_n_min", "spec_p_min"}

    if not _takes_draft_model(types):
        # every ngram-* type runs without a separate draft GGUF. draft-mtp is
        # NOT dropped here: it may or may not need one, so the key stays live
        # and emits whenever a path is actually set.
        keys -= {"draft_model", "spec_ngl"}
    return keys


def editable_keys(values):
    """Which setting keys the board prompts for. Same gating as emission, except
    spec_type is always editable - otherwise row 10 could never be switched on,
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
