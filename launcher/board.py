"""Terminal UI: the config menu and the settings board."""
import json
import os

from . import catalog


def _bad(label, value):
    """How a wrong-typed value is shown.

    The board renders BEFORE anything can be edited, so a value the catalog
    cannot make sense of must still reach the screen: raising here locks the
    user out of the one screen that could repair the file. Marked the way
    render_menu marks a missing model, and the value itself is printed
    unchanged - it is what the user has to recognise in their editor."""
    return f"{label} !bad {value}"


# Values that llama-server spells as a number and means as a word. Display
# only - emit() still sends the number. gpu_layers already shows "auto" because
# its default IS the string "auto", and a board that prints "auto" on one row
# and "-1" on another for the same idea is leaking an implementation detail.
_SENTINELS = {
    ("parallel", -1): "auto",                  # choose a slot count for me
    ("reasoning_budget", -1): "unrestricted",  # no limit on thinking tokens
}


def _fmt(setting, value):
    if value is None:
        # A dash, for EVERY type including tri. The row still tells the user the
        # setting exists while being honest that WE are not setting it -
        # llama-server's own default applies - and the dash is what you type to
        # put one back.
        #
        # Tri-states used to vanish here instead, on the grounds that "off"
        # would claim we pass --no-flag when we pass nothing at all. That much
        # is true of "off" and not of "-", and the cost of vanishing was the
        # whole setting: reasoning_preserve was in the catalog, editable, and
        # emitting - and the board never once mentioned it, so preserving
        # thinking looked like a job for a hand-written template kwarg.
        return f"{setting.label} -"
    # Guarded by isinstance rather than looked up directly: a hand-edited config
    # can put a list or a dict on any key, and hashing one inside this tuple
    # raises TypeError - from the render, which is the one screen the bad value
    # could be repaired from. bool is excluded because True == 1 in Python, so a
    # toggle must never borrow a number's word for itself.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        sentinel = _SENTINELS.get((setting.key, value))
        if sentinel:
            return f"{setting.label} {sentinel}"
    if setting.type == "bool":
        return f"{setting.label} {'on' if value else 'off'}"
    if setting.type == "tri":
        return f"{setting.label} {value}"
    if setting.type == "json":
        if not isinstance(value, dict):
            return _bad(setting.label, value)
        if not value:
            return "(none)"
        return "  ".join(f"{k}={json.dumps(v)}" for k, v in value.items())
    if setting.type == "raw":
        if not isinstance(value, str):
            return _bad(setting.label, value)
        if not value:
            return "(none)"
        # Unbalanced quotes are rejected at edit time but survive a hand edit,
        # and emit() then silently drops the whole row. Say so here, or the
        # board shows arguments the launch is not actually passing.
        ok, _ = catalog.split_extra(value)
        return value if ok else _bad(setting.label, value)
    return f"{setting.label} {value}"


def render_group(group, values):
    """One board row's value column."""
    if group.key == "context":
        return str(values.get("context"))
    if group.key == "gpu":
        return str(values.get("gpu_layers"))
    if group.key == "net":
        return f"{values.get('host')}:{values.get('port')}"
    if group.key == "kv":
        return f"K {values.get('cache_type_k')} / V {values.get('cache_type_v')}"

    if group.key == "spec":
        # Through spec_types_of rather than off the dict: that is where the
        # coercion lives, so a hand-edited number on this key renders instead of
        # taking the whole board down with it.
        types = ",".join(catalog.spec_types_of(values))
        if types == "none":
            return "none"
        parts = [types]
        if catalog.spec_carries_own_head(values):
            # draft-mtp and every ngram-* type: the model carries its own
            # prediction head. Asking the catalog rather than listing the type
            # names keeps this from drifting when it gains a type - and asking
            # spec_carries_own_head rather than active_keys is what stops the
            # note being printed about a type nobody recognises. active_keys
            # drops draft_model for a typo'd 'ngram-modd' too, so the row used
            # to claim a built-in prediction head for a string the catalog
            # cannot read, next to a draft model it was about to delete.
            parts.append("(built-in, no draft model)")
        else:
            if values.get("draft_model"):
                parts.append(os.path.basename(str(values["draft_model"])))
            # spec_ngl is only meaningful with a separate draft model, but it IS
            # editable, and a setting the user can change must be visible.
            ngl = catalog.settings_by_key()["spec_ngl"]
            parts.append(f"{ngl.label} {values.get('spec_ngl')}")
        for key in ("spec_n_max", "spec_n_min", "spec_p_min"):
            setting = catalog.settings_by_key()[key]
            parts.append(f"{setting.label} {values.get(key)}")
        return "  ".join(parts)

    rendered = [_fmt(s, values.get(s.key)) for s in group.settings]
    rendered = [r for r in rendered if r]
    return "  ".join(rendered) if rendered else "(none)"


def render_board(values, dirty, header):
    lines = [header, ""]
    for i, group in enumerate(catalog.GROUPS, 1):
        mark = "*" if group.key in dirty else " "
        lines.append(f"{mark}{i:>2}  {group.label:<12} {render_group(group, values)}")
    # Derived, not hardcoded: a hardcoded "[1-10]" silently lies the moment a
    # row is added, and the whole point of the catalog is that rows can be added.
    lines += ["", f"  [1-{len(catalog.GROUPS)}] edit   [s] save   [c] show command   "
                  f"[Enter] launch   [q] back"]
    return "\n".join(lines)


def _size_label(size):
    """Human file size, or blank padding when the size is unknown."""
    if not size:
        return " " * 8
    return f"{size / 1024 ** 3:>5.1f} GB"


# Every character PowerShell's own parser reads as anything but text, so a token
# holding one of these has to be quoted before PowerShell sees it. Verified on
# 5.1.26100.9168 rather than copied from a list: a bare & is a parse error, a
# bare | starts a pipeline, and both do it inside a --% tail as well. % is here
# because a --% tail expands cmd-style %NAME% even inside quotes, and the
# newline because it ends a --% tail outright.
_PS_SPECIAL = " \t\r\n\"'`$&|<>(){}[];,@#%"


def _crt_argument(arg, ps_safe=False):
    """One argument, encoded the way the Windows C runtime decodes a command
    line back into argv: quoted if it holds whitespace or a quote, an embedded
    quote written \\", and a backslash run doubled when it sits immediately
    before a quote or at the end of a quoted argument.

    The doubling is not decoration. \\" is how that runtime writes a literal
    quote, so an odd run would escape one of ours and swallow every following
    argument into this one - a model path like D:\\LLM Models\\ is the everyday
    case, and it did exactly that.

    \\" AND NOT THE OTHER LEGAL SPELLING. A doubled "" inside a quoted run also
    means a literal quote - split_extra decodes that form for the extra-args row
    - and it would be convenient here, because it keeps PowerShell's quote count
    even (see _ps_requotes). It is not used, because the receiving binary does
    not decode it reliably: fed straight to CreateProcess, build 10453 read
        "{""a"":""b c""}"   as   {"a":"b c"}     (right)
        "a ""b c"" d"       as   a "b  /  c  /  d"  (three arguments)
    while every \\" form in the same matrix came back byte for byte. What the
    binary actually decodes wins over what would be convenient here.

    ps_safe widens the quoting to every character PowerShell's parser treats as
    an operator. It changes nothing for the C runtime - a quoted argument with
    no whitespace decodes the same - but it puts a bar or an ampersand inside a
    string as far as PowerShell's tokenizer is concerned, which is what the --%
    tail needs.

    Verified by feeding these forms to the real llama-server.exe --model
    nonexistent.gguf and reading back the argument it reports: quotes, spaces,
    tabs, newlines, pipes, trailing backslashes and empty arguments all arrive
    intact."""
    if not isinstance(arg, str):
        # A hand-edited config can put a number where argv wants a string (an
        # alias, most easily). [c] is a display path, and taking it down with a
        # TypeError would hide the very command the user pressed [c] to inspect.
        arg = str(arg)
    # Any whitespace, not just space and tab. The C runtime itself breaks
    # arguments on space and tab only, so a bare newline would survive it - but
    # PowerShell decides whether to re-quote with char.IsWhiteSpace, which counts
    # newlines, vertical tabs and no-break spaces too. Quoting them here means
    # PowerShell finds every such argument already quoted and adds nothing, so
    # one encoding covers both readers instead of two that disagree.
    bare = not any(c.isspace() or c == '"' for c in arg)
    if ps_safe:
        bare = bare and not any(c in _PS_SPECIAL for c in arg)
    if arg and bare:
        return arg
    out, run = [], 0
    for ch in arg:
        if ch == "\\":
            run += 1
            continue
        if ch == '"':
            out.append("\\" * (run * 2 + 1))    # double the run, escape the quote
            out.append('"')
        else:
            out.append("\\" * run)
            out.append(ch)
        run = 0
    out.append("\\" * (run * 2))                # trailing run precedes our quote
    return '"' + "".join(out) + '"'


def _ps_command(path):
    """The executable, quoted for PowerShell's parser only.

    This one is a command NAME, not an argument: PowerShell resolves it and
    hands it to CreateProcess itself, so it never passes through the native
    argument re-quoting that _crt_argument and the marker exist to escape."""
    if not isinstance(path, str):
        path = str(path)
    if path and not any(c in path for c in _PS_SPECIAL):
        return path
    return "'" + path.replace("'", "''") + "'"


def _ps_literal(text):
    """PowerShell source that evaluates to exactly `text`.

    Single quotes are PowerShell's one literal quoting: no $ expansion, no
    backtick escapes, no operators, and '' for a literal quote inside. A token
    with nothing special in it is left bare, because the whole point of [c] is
    that somebody reads the line."""
    if text and not any(c in text for c in _PS_SPECIAL):
        return text
    return "'" + text.replace("'", "''") + "'"


def _ps_requotes(text):
    """Whether PowerShell 5.1 will REWRITE this string on its way to a native
    command, instead of passing it on as it stands.

    Measured on 5.1.26100.9168, not assumed. PowerShell walks the value keeping
    a running count of quote CHARACTERS - every one of them, a backslash-escaped
    \\" included, which is the half that has to be measured - and decides it must
    re-quote the moment it meets whitespace while that count is even. When it
    decides that, it wraps the value in quotes and does NOT escape the quotes
    already inside it, so the argument stops being the argument:
        value    "{\\"a\\":\\"b c\\"}"     four quotes before the space, so even
        sent     ""{\\"a\\":\\"b c\\"}""
        received {"a":"b   and   c"}     - two arguments
    That wrapping is also the lever _ps_argument uses: when it is going to
    happen anyway, handing PowerShell the BODY of the encoding lets its own
    quotes become the outer pair."""
    quotes = 0
    for ch in text:
        if ch == '"':
            quotes += 1
        elif ch.isspace() and quotes % 2 == 0:
            return True
    return False


def _ps_argument(arg):
    """One argv entry as PowerShell source, or None if PowerShell 5.1 cannot
    carry this one at all without the stop-parsing marker.

    Two readers in a row, and they are not the same reader. PowerShell's parser
    turns the pasted text into a string value; PowerShell then rebuilds a
    command line for the native process, re-quoting per _ps_requotes. So there
    are exactly two shapes that survive, and which one applies is decided, not
    guessed:

      * PowerShell will not re-quote the encoding -> hand it the encoding, and
        it copies it onto the command line untouched.
      * PowerShell will re-quote, but it would not re-quote the BODY (the
        encoding without its outer quotes) - then hand it the body, because
        wrapping the body in quotes is precisely what re-quoting does, and the
        result is the encoding again. This is what carries an alias like
            say "hi there" now
        which has whitespace on both sides of its quotes.

    Neither shape exists when EVERY whitespace in the argument follows an odd
    number of quotes - a JSON value with a space in it, {"a":"b c"}, is the
    everyday case. The count at that space is then even whichever way the outer
    quotes fall, so PowerShell re-quotes both shapes and mangles both. Nothing
    can be escaped around it; the argument's own content sets the count. That is
    what None reports, and as_powershell answers it with the marker."""
    encoded = _crt_argument(arg)
    if not _ps_requotes(encoded):
        return _ps_literal(encoded)
    if len(encoded) >= 2 and encoded.startswith('"') and encoded.endswith('"'):
        body = encoded[1:-1]
        # A body ending in a backslash is left out on purpose: PowerShell adds
        # one of its own before the closing quote it appends, which would turn
        # our doubled run odd and escape that quote.
        if _ps_requotes(body) and not body.endswith("\\"):
            return _ps_literal(body)
    return None


def as_powershell(argv):
    """argv -> a PowerShell command line that can be pasted and run.

    The leading & is PowerShell's call operator, needed whenever the executable
    path is quoted and harmless when it is not. What follows is one of two
    forms, and the choice between them is the fix.

    THE QUOTED FORM, used whenever it can carry every argument. Each argument is
    a single-quoted PowerShell literal, so PowerShell's parser reads a bar, an
    ampersand, a semicolon, a percent sign, a dollar sign and a newline inside
    one as plain text, and _ps_argument arranges that the value PowerShell then
    builds a command line from is the encoding the binary wants.

    THE MARKER FORM, & exe --% ..., used only when the quoted form cannot carry
    some argument - which means an argument whose every whitespace follows an
    odd number of its own quotes, {"a":"b c"} being the everyday case. --% is
    PowerShell's stop-parsing marker: the tail reaches the process as written,
    which is the only way that argument gets there whole.

    WHY THE MARKER IS NO LONGER THE DEFAULT, which is what it used to be. It is
    documented to be "effective only until the next newline or pipeline
    character", and that is not a footnote. Verified on PowerShell 5.1.26100.9168
    against the real llama-server.exe:
        & llama-server.exe --% --model nonexistent.gguf --alias qwen|draft
    PowerShell ends the verbatim run at the bar, tries to run `draft` as a
    command, and reports CommandNotFoundException - the alias and every argument
    after it silently gone from the command the user was told to trust. A
    newline ends the tail the same way and cannot be quoted out of it at all,
    and the tail expands cmd-style %NAME% into real environment variables even
    inside quotes. The quoted form has none of those, so it goes first and the
    marker is the fallback rather than the rule.

    WHAT THE MARKER FORM STILL CANNOT DO, said out loud because it is now
    reached only by arguments that leave no choice: a bar or an ampersand inside
    such an argument sits at an even quote count for PowerShell's tokenizer too,
    so {"a":"b|c"} in the same command as a spaced JSON value would still break.
    ps_safe quoting covers every simpler case - a bare qwen|draft is quoted and
    arrives intact - and a newline in that position cannot be expressed by any
    single pasted PowerShell line.

    The launch itself never goes near any of this: spawn() passes argv as a list
    and no command string is ever built. This function exists purely so the
    command shown by [c] can be pasted into the shell this user works in."""
    if not argv:
        return "&"
    head = _ps_command(argv[0])
    quoted = [_ps_argument(a) for a in argv[1:]]
    if all(q is not None for q in quoted):
        rest = " ".join(quoted)
        return "& " + head + (" " + rest if rest else "")
    rest = " ".join(_crt_argument(a, ps_safe=True) for a in argv[1:])
    return "& " + head + (" --% " + rest if rest else "")


def dispatch(key):
    key = (key or "").strip().lower()
    if key == "":
        return "launch"
    # isdecimal, NOT isdigit. isdigit() accepts characters int() then rejects -
    # superscript two is the clearest case: "²".isdigit() is True but
    # int("²") raises ValueError, crashing the launcher on a pasted
    # character. isdecimal() still accepts genuine non-ASCII digits such as
    # Arabic-Indic "٣", which int() converts correctly to 3.
    if key.isdecimal():
        try:
            n = int(key)
        except ValueError:
            # isdecimal() is not enough on its own: int() refuses a decimal
            # string longer than 4300 digits (CPython's integer-string
            # conversion limit) and raises ValueError. A pasted wall of digits
            # is no more a row number than "abc" is, and the contract here is
            # that nothing typed at this prompt escapes as an exception.
            return "unknown"
        return f"edit:{n}" if 1 <= n <= len(catalog.GROUPS) else "unknown"
    return {"s": "save", "c": "command", "q": "quit"}.get(key, "unknown")


def _prompt_for(setting, current):
    hint = ""
    if setting.type == "choice":
        hint = "  (" + ", ".join(setting.choices) + ")"
    elif setting.type == "spec_type":
        hint = "  (" + ", ".join(catalog.SPEC_TYPES) + ")"
    elif setting.type == "tri":
        hint = "  (on / off / - to leave it to llama-server)"
    elif setting.type == "bool":
        hint = "  (y/n)"
    if setting.default is None and setting.type not in ("tri", "bool"):
        hint += "  (- for the llama-server default)"
    shown = "-" if current is None else current
    if setting.type == "json" and isinstance(current, dict):
        shown = json.dumps(current) if current else ""
    return f"  {setting.label}{hint} [{shown}]: "


def edit_group(group, values, ask, say):
    """Walk one row's settings. Blank keeps the current value; invalid input
    re-prompts. `ask` and `say` are injected so this is testable headless."""
    values = dict(values)
    for setting in group.settings:
        # Recomputed per setting: answering spec_type changes what comes after it.
        if setting.key not in catalog.editable_keys(values):
            continue
        while True:
            answer = ask(_prompt_for(setting, values.get(setting.key)))
            # Blank keeps the current value for EVERY type. The tri types used
            # to be excepted here so blank could mean "unset", but the prompt
            # shows the current value in brackets and the spec says Enter
            # accepts - so pressing Enter through this row wiped saved settings.
            # Clearing is "-", uniformly.
            if (answer or "").strip() == "":
                break
            ok, result = catalog.parse_value(setting, answer)
            if ok:
                values[setting.key] = result
                break
            say(f"    {result}")

    # Switching to a spec type that carries its own prediction head leaves a
    # stale draft_model behind. editable_keys then hides that row, so the user
    # cannot reach it - yet spec_error refuses to launch and tells them to
    # "clear the draft model row". That is an instruction the UI cannot obey.
    # Clear it here and say so, rather than stranding them.
    #
    # Asked of catalog.spec_carries_own_head, NOT of editable_keys. The two
    # differ on exactly the case this row exists to repair: active_keys drops
    # draft_model for any type that is not a known draft-* type, an UNKNOWN one
    # included, so a hand-edited "ngram-modd" took this branch. spec_error sends
    # the user to row 10 to fix that typo; pressing Enter through the row - blank
    # keeps, so the typo is still there - then deleted their draft model and
    # told them "ngram-modd carries its own", which is not true of a string the
    # catalog cannot interpret at all. The row was marked dirty afterwards, so
    # [s] made the loss permanent. An unrecognised type is left alone; only a
    # type we actually recognise as carrying its own head clears anything.
    if (group.key == "spec" and values.get("draft_model")
            and catalog.spec_carries_own_head(values)):
        types = ",".join(catalog.spec_types_of(values))
        say(f"    cleared the draft model: {types} carries its own")
        values["draft_model"] = None
    return values


def render_menu(configs, missing, sizes=None):
    """`sizes` maps config name to file size in bytes. Sizes are shown because
    two of these models exceed the card's VRAM, so the number is decision-
    relevant rather than decoration."""
    sizes = sizes or {}
    lines = ["Available launch configs:", ""]
    for i, cfg in enumerate(configs, 1):
        mark = "  !missing" if cfg["name"] in missing else ""
        lines.append(f"  {i:>2}  {cfg['name']:<32} "
                     f"{os.path.basename(cfg['model']):<44} "
                     f"{_size_label(sizes.get(cfg['name']))}{mark}")
    lines += ["", "  [n] new config from a .gguf   [q] quit"]
    return "\n".join(lines)
