"""Terminal UI: the config menu and the settings board."""
import json
import os

from . import catalog


def _fmt(setting, value):
    if value is None:
        return None
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
            parts.append("(built-in, no draft model)")
        elif values.get("draft_model"):
            parts.append(os.path.basename(str(values["draft_model"])))
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
        lines.append(f"{mark}{i:>3}  {group.label:<12} {render_group(group, values)}")
    lines += ["", "  [1-10] edit   [s] save   [c] show command   "
                  "[Enter] launch   [q] back"]
    return "\n".join(lines)


def render_menu(configs, missing):
    lines = ["Available launch configs:", ""]
    for i, cfg in enumerate(configs, 1):
        mark = "  !missing" if cfg["name"] in missing else ""
        lines.append(f"  {i:>2}  {cfg['name']:<32} "
                     f"{os.path.basename(cfg['model'])}{mark}")
    lines += ["", "  [n] new config from a .gguf   [q] quit"]
    return "\n".join(lines)
