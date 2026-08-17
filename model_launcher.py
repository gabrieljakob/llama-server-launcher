#!/usr/bin/env python3
"""
Interactive LLM model launcher
Scans D:/LLM Models for .gguf files and lets you pick one to start llama-server.
"""
import os
import sys
import subprocess
import glob
import json

MODEL_ROOT = r"D:\LLM Models"
LLAMA_SERVER = r"D:\llama.cpp\llama-server.exe"
PROFILES_PATH = os.path.join(os.path.dirname(__file__), "model_profiles.json")

def load_profiles():
    with open(PROFILES_PATH, encoding="utf-8") as f:
        return json.load(f)

def find_models():
    pattern = os.path.join(MODEL_ROOT, "**", "*.gguf")
    files = glob.glob(pattern, recursive=True)
    models = [f for f in files if "mmproj" not in os.path.basename(f).lower()]
    return sorted(models)

def infer_flags_from_name(name):
    # Simple heuristics based on model name patterns
    n = name.lower()
    flags = {}
    # Context heuristics
    if "35b" in n or "30b" in n or "27b" in n or "28b" in n:
        flags["context"] = 32768
    elif "12b" in n:
        flags["context"] = 8192
    elif "7b" in n:
        flags["context"] = 4096
    else:
        flags["context"] = 8192
    # Temperature heuristics
    if "chat" in n or "it" in n:
        flags["temp"] = 0.6
    else:
        flags["temp"] = 0.7
    # Top-k heuristics
    if "q4" in n:
        flags["top_k"] = 20
    elif "q3" in n:
        flags["top_k"] = 40
    else:
        flags["top_k"] = 40
    return flags

def canon(path):
    # Canonical form for comparing paths: normalizes separators, and case on Windows
    return os.path.normcase(os.path.normpath(path))

def pretty_name(path):
    rel = os.path.relpath(path, MODEL_ROOT)
    return rel.replace("\\", "/")

def merge_flags(defaults, overrides):
    merged = defaults.copy()
    merged.update(overrides or {})
    return merged

def build_model_list(model_defs, scanned, exists=os.path.exists):
    # Profiled models first, then any scanned model no profile already covers.
    # Profiles are written with forward slashes but glob returns backslashes,
    # so both sides go through canon() before comparing.
    models = []
    for m in model_defs:
        path = os.path.normpath(m["path"])
        if exists(path):
            models.append({"name": m["name"], "path": path, "alias": m.get("alias", ""), "overrides": m.get("overrides", {})})

    profile_paths = {canon(m["path"]) for m in model_defs}
    for p in scanned:
        if canon(p) not in profile_paths:
            name = os.path.splitext(os.path.basename(p))[0]
            inferred = infer_flags_from_name(name)
            models.append({"name": name, "path": p, "alias": name, "overrides": inferred})
    return models

def main():
    profiles = load_profiles()
    defaults = profiles.get("defaults", {})
    model_defs = profiles.get("models", [])

    models = build_model_list(model_defs, find_models())

    if not models:
        print("No GGUF models found in", MODEL_ROOT)
        sys.exit(1)

    print("Available LLM models:")
    for i, m in enumerate(models, 1):
        print(f"{i}. {m['name']}  ({pretty_name(m['path'])})")

    try:
        choice = int(input("\nSelect model number: ").strip())
        if not 1 <= choice <= len(models):
            raise ValueError
    except ValueError:
        print("Invalid selection")
        sys.exit(1)

    sel = models[choice-1]
    model_path = sel["path"]
    alias = sel["alias"] or os.path.splitext(os.path.basename(model_path))[0]

    flags = merge_flags(defaults, sel["overrides"])

    print(f"\nStarting llama-server with model: {sel['name']}")
    print(f"Flags: ngl={flags.get('ngl')}, context={flags.get('context')}, temp={flags.get('temp')}, top_k={flags.get('top_k')}, top_p={flags.get('top_p')}")
    cmd = [
        LLAMA_SERVER,
        "--model", model_path,
        "--alias", alias,
        "-ngl", str(flags.get("ngl", 99)),
        "-c", str(flags.get("context", 8192)),
        "--host", flags.get("host", "127.0.0.1"),
        "--port", str(flags.get("port", 1234)),
        "--temp", str(flags.get("temp", 0.6)),
        "--top-k", str(flags.get("top_k", 20)),
        "--top-p", str(flags.get("top_p", 0.95)),
        "--min-p", str(flags.get("min_p", 0.0)),
        "--jinja",
        "--no-mmproj",
    ]
    if flags.get("flash_attn"):
        cmd.extend(["--flash-attn", "on"])

    os.system("taskkill /F /IM llama-server.exe >nul 2>&1")
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    print("Server started in new window.")

if __name__ == "__main__":
    main()
