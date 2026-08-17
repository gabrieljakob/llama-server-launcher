"""Terminal UI: the config menu and the settings board."""
import json
import os

from . import catalog


def _fmt(setting, value):
    if value is None:
        # A tri-state vanishes when unset: showing "off" would claim we pass
        # --no-flag when we pass nothing at all. A valued setting instead shows
        # a dash, so the row still tells the user the setting exists while being
        # honest that WE are not setting it - llama-server's own default applies.
        # The dash is also what you type to put one back.
        return None if setting.type == "tri" else f"{setting.label} -"
    if setting.key == "parallel" and value == -1:
        # -1 is llama-server's sentinel for "choose a slot count for me". Show
        # what it means, not the sentinel: gpu_layers already displays "auto"
        # because its default IS the string "auto", and a board that prints
        # "auto" on one row and "-1" on another for the same concept is just
        # leaking an implementation detail. Display only - emit() still sends -1.
        return f"{setting.label} auto"
    if setting.type == "bool":
        return f"{setting.label} {'on' if value else 'off'}"
    if setting.type == "tri":
        return f"{setting.label} {value}"
    if setting.type == "json":
        if not value:
            return "(none)"
        return "  ".join(f"{k}={json.dumps(v)}" for k, v in value.items())
    if setting.type == "raw":
        return value if value else "(none)"
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
        types = values.get("spec_type") or "none"
        if types == "none":
            return "none"
        live = catalog.active_keys(values)
        parts = [types]
        if "draft_model" not in live:
            # draft-mtp and every ngram-* type: the model carries its own
            # prediction head. Asking active_keys rather than listing the type
            # names keeps this from drifting when the catalog gains a type.
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


_PS_SPECIAL = " \t\"'`$&|<>(){}[];,@#"


def _ps_quote(arg):
    """Quote one argument for Windows PowerShell 5.1 invoking a native exe.

    TWO layers, both required. Verified empirically against llama-server:

      '{"k":true}'     REJECTED - PowerShell 5.1 strips embedded double quotes
                       when handing a string to a native command, so the binary
                       receives {k:true} and its JSON parser refuses it.
      "{\\"k\\":true}"   REJECTED - double-quoted strings interpolate.
      '{\\"k\\":true}'   WORKS - the backslashes let the receiving C runtime
                       recover the quotes, and the single quotes stop PowerShell
                       touching the backslashes on the way through.

    subprocess.list2cmdline is NOT used here: it emits the CreateProcess
    convention, which cmd.exe and Popen understand but PowerShell mangles. The
    actual launch is unaffected either way - spawn() passes argv as a list and
    never builds a command string - this function exists purely so the command
    shown by [c] can be pasted into the shell this user actually works in."""
    if arg and not any(c in arg for c in _PS_SPECIAL):
        return arg
    return "'" + arg.replace('"', '\\"').replace("'", "''") + "'"


def as_powershell(argv):
    """argv -> a PowerShell command line that can be pasted and run.

    The leading & is PowerShell's call operator, needed whenever the executable
    path is quoted and harmless when it is not."""
    return "& " + " ".join(_ps_quote(a) for a in argv)


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
        n = int(key)
        return f"edit:{n}" if 1 <= n <= len(catalog.GROUPS) else "unknown"
    return {"s": "save", "c": "command", "q": "quit"}.get(key, "unknown")


def _prompt_for(setting, current):
    hint = ""
    if setting.type == "choice":
        hint = "  (" + ", ".join(setting.choices) + ")"
    elif setting.type == "spec_type":
        hint = "  (" + ", ".join(catalog.SPEC_TYPES) + ")"
    elif setting.type == "tri":
        hint = "  (on / off / blank = leave to llama-server)"
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
            if (answer or "").strip() == "" and setting.type != "tri":
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
    if (group.key == "spec" and values.get("draft_model")
            and "draft_model" not in catalog.editable_keys(values)):
        say(f"    cleared the draft model: {values['spec_type']} carries its own")
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
