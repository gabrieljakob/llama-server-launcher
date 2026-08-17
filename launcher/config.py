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


def _migrate_settings(old):
    out = {}
    for old_key, value in (old or {}).items():
        key = _MIGRATE_KEYS.get(old_key)
        if key is None:
            continue
        if key == "gpu_layers":
            value = str(value)
        elif key == "flash_attn":
            value = "on" if value is True else ("off" if value is False else value)
        out[key] = value
    return out


def migrate(profiles, model_root, llama_server):
    """model_profiles.json -> the v2 document. Returns (document, report lines)."""
    report = []
    doc = {"version": 2, "model_root": model_root, "llama_server": llama_server,
           "defaults": _migrate_settings(profiles.get("defaults")), "configs": []}

    for entry in profiles.get("models", []):
        name = entry.get("alias") or entry.get("name")
        model = relativise(entry["path"].replace("/", os.sep), model_root)
        doc["configs"].append({
            "name": name,
            "model": model,
            "alias": entry.get("alias") or name,
            "settings": _migrate_settings(entry.get("overrides")),
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
