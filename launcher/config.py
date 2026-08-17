"""Loading, resolving and persisting launcher configs."""
import json
import os

from . import catalog


class ConfigError(Exception):
    pass


def canon(path):
    """Canonical form for comparing paths: separators, and case on Windows."""
    return os.path.normcase(os.path.normpath(path))


def resolve_path(path, model_root):
    """Config-relative path -> absolute path."""
    if os.path.isabs(path):
        return path
    return os.path.join(model_root, os.path.normpath(path))


def relativise(path, model_root):
    """Absolute path -> model_root-relative, with forward slashes. Paths outside
    model_root are returned unchanged."""
    root = canon(model_root)
    full = canon(path)
    if full.startswith(root + os.sep):
        return os.path.relpath(path, model_root).replace("\\", "/")
    return path


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid JSON: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}. The file was not modified.")
    except UnicodeDecodeError as exc:
        # Not a subclass of JSONDecodeError, and not of OSError either: it is a
        # ValueError, so it escaped both guards below. Editors on this machine
        # default to cp1252, so saving a config with one umlaut in a model name
        # is enough to produce a file we cannot decode as UTF-8.
        raise ConfigError(
            f"{path} is not UTF-8 text: {exc.reason} at byte {exc.start}. "
            f"Re-save it as UTF-8. The file was not modified.")
    except OSError as exc:
        # A locked, unreadable or replaced-by-a-directory config is the same
        # kind of problem to the user as a malformed one, and must report the
        # same way rather than as a traceback.
        raise ConfigError(f"cannot read {path}: {exc}")


def document_error(data, path):
    """Why `data` is not a usable v2 document, or None if it is.

    Every one of these reached the user as a bare KeyError or TypeError from a
    file they had just hand-edited themselves - a traceback that named a Python
    line instead of the key they had deleted. Checked once, up front, because
    the values are read from a dozen places afterwards and guarding each of
    them separately would guarantee one gets missed."""
    if not isinstance(data, dict):
        return f"{path}: the top level must be a JSON object"
    for key in ("model_root", "llama_server"):
        if key not in data:
            return f"{path}: no {key!r} key"
        if not isinstance(data[key], str):
            return f"{path}: {key!r} must be a string path"
    if not isinstance(data.get("defaults", {}), dict):
        return f"{path}: 'defaults' must be a JSON object"
    if "configs" not in data:
        return f"{path}: no 'configs' key"
    if not isinstance(data["configs"], list):
        return f"{path}: 'configs' must be a list"
    for index, cfg in enumerate(data["configs"], 1):
        if not isinstance(cfg, dict):
            return f"{path}: config {index} must be a JSON object"
        for key in ("name", "model"):
            if key not in cfg:
                return f"{path}: config {index} has no {key!r} key"
            if not isinstance(cfg[key], str):
                return f"{path}: config {index} has a non-string {key!r}"
        if not isinstance(cfg.get("settings", {}), dict):
            return (f"{path}: config {cfg['name']!r} has a 'settings' that is "
                    f"not a JSON object")
    return None


def resolve_values(data, cfg):
    """Four-layer resolution: catalog -> file defaults -> config settings.
    Board edits are layered on top by the caller."""
    values = catalog.catalog_defaults()
    known = set(values)
    for layer in (data.get("defaults") or {}, cfg.get("settings") or {}):
        for key, value in layer.items():
            if key in known:
                values[key] = value
    return values


# Old model_profiles.json key -> new catalog key
_MIGRATE_KEYS = {"ngl": "gpu_layers", "context": "context", "host": "host",
                 "port": "port", "temp": "temp", "top_k": "top_k",
                 "top_p": "top_p", "min_p": "min_p", "flash_attn": "flash_attn"}

# GGUFs that are draft models rather than standalone models. Named here because
# the old format had no way to express the distinction.
_LIKELY_DRAFT = ("dflash", "dspark")


def _migrate_settings(old, where, report):
    """Old-format settings -> catalog keys. Unmapped keys are dropped silently;
    values we cannot interpret are dropped loudly, into `report`."""
    out = {}
    if old is not None and not isinstance(old, dict):
        report.append(f"  WARNING: {where} had settings that are not a JSON "
                      f"object ({old!r}). Dropped; the defaults apply.")
        return out
    for old_key, value in (old or {}).items():
        key = _MIGRATE_KEYS.get(old_key)
        if key is None:
            continue
        if key == "gpu_layers":
            value = str(value)
        elif key == "flash_attn":
            # The old format wrote a bool. A hand-edited file might hold anything;
            # guessing an intent would emit an invalid flag value that only fails
            # much later, at server start, with nothing pointing back to here.
            if isinstance(value, bool):
                value = "on" if value else "off"
            elif value not in ("on", "off", "auto"):
                report.append(
                    f"  WARNING: {where} had flash_attn={value!r}, which is neither a "
                    f"bool nor one of on/off/auto. Dropped; the default applies.")
                continue
        out[key] = value
    return out


def migrate(profiles, model_root, llama_server):
    """model_profiles.json -> the v2 document. Returns (document, report lines).

    Never mutates `profiles`, and never touches model_profiles.json on disk: that
    file is the user's rollback path."""
    report = []
    if not isinstance(profiles, dict):
        # The whole legacy file is something other than an object. Nothing to
        # read, but an empty v2 document still lets the launcher start.
        report.append("  SKIPPED the whole file: model_profiles.json does not "
                      "contain a JSON object. Nothing was migrated.")
        profiles = {}
    doc = {"version": 2, "model_root": model_root, "llama_server": llama_server,
           "defaults": _migrate_settings(profiles.get("defaults"), "defaults", report),
           "configs": []}

    models = profiles.get("models", [])
    if not isinstance(models, list):
        report.append(f"  SKIPPED every entry: 'models' is a "
                      f"{type(models).__name__}, not a list. Nothing was migrated.")
        models = []

    for index, entry in enumerate(models, 1):
        # A partial or hand-edited entry must not abort the whole migration -
        # this runs once, on the user's only config, and losing five good
        # configs to one malformed sixth would be a poor trade. Wrong SHAPE is
        # the same trade: a bare string in the list, or a path written as a
        # number, used to end the migration with an AttributeError instead.
        if not isinstance(entry, dict):
            report.append(f"  SKIPPED entry {index}: not a JSON object. "
                          f"Other entries were unaffected.")
            continue
        name = entry.get("alias") or entry.get("name")
        path = entry.get("path")
        if not path or not name:
            missing = "path" if not path else "name/alias"
            report.append(f"  SKIPPED entry {index}: no {missing}. "
                          f"Other entries were unaffected.")
            continue
        if not isinstance(path, str) or not isinstance(name, str):
            bad = "path" if not isinstance(path, str) else "name/alias"
            report.append(f"  SKIPPED entry {index}: {bad} is not a string. "
                          f"Other entries were unaffected.")
            continue

        model = relativise(path.replace("/", os.sep), model_root)
        doc["configs"].append({
            "name": name,
            "model": model,
            "alias": entry.get("alias") or name,
            "settings": _migrate_settings(entry.get("overrides"), f"config {name!r}",
                                          report),
        })
        report.append(f"  migrated config {name!r} -> {model}")
        if any(hint in model.lower() for hint in _LIKELY_DRAFT):
            report.append(
                f"  NOTE: {name!r} looks like a draft model, not a standalone one. "
                f"Consider deleting this config and attaching the GGUF to another "
                f"config's speculative row instead.")

    report.append(f"  wrote {len(doc['configs'])} configs; "
                  f"model_profiles.json left untouched as a rollback")
    return doc, report


def diff_from_defaults(data, values):
    """Only the values that differ from catalog defaults overlaid with file
    defaults. Saving the fully resolved set instead would copy every value into
    every config, and later edits to `defaults` would stop reaching them."""
    base = catalog.catalog_defaults()
    for key, value in (data.get("defaults") or {}).items():
        if key in base:
            base[key] = value
    return {k: v for k, v in values.items() if k in base and v != base[k]}


def _temp_path(path):
    """Scratch path for an atomic save.

    Same directory as the target, because os.replace is only atomic within one
    volume. Process-qualified, because two launcher instances saving at once
    would otherwise race on one filename and the loser would fail with a
    PermissionError it could not explain."""
    folder = os.path.dirname(os.path.abspath(path))
    return os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.tmp")


def save(path, data):
    """Write atomically: a crash mid-write must not truncate the config file."""
    tmp = _temp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        # One exception type for callers to catch, matching load(). A read-only
        # folder or a full disk used to come out of [s] as a traceback, ending
        # the session and taking every unsaved board edit with it - the exact
        # work the user pressed [s] to protect.
        raise ConfigError(f"could not write {path}: {exc}") from exc
