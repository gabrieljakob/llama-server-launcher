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
