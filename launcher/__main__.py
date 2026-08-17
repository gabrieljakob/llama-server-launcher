"""Entry point. Wiring only - the logic lives in the other four modules."""
import glob
import os
import subprocess
import sys

from . import board, catalog, config, server

# This machine's console is cp1252 (German Windows). Any non-ASCII character
# reaching print() raises UnicodeEncodeError and kills the launcher mid-session.
# Model filenames and llama-server paths are user data and can contain anything,
# so widen stdout rather than trusting every string to stay ASCII.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass                      # already-wrapped or redirected stream: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(SCRIPTS, "launcher_configs.json")
LEGACY_PATH = os.path.join(SCRIPTS, "model_profiles.json")

DEFAULT_ROOT = r"D:\LLM Models"
DEFAULT_EXE = r"D:\llama.cpp\llama-server.exe"


def ask(prompt=""):
    """input() that treats EOF and Ctrl-C as "quit" instead of a traceback.

    A piped, redirected or closed stdin makes input() raise EOFError, and Ctrl-C
    raises KeyboardInterrupt. Either would end the session with a stack trace
    across the user's console. Every prompt in this module goes through here."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def first_run_migration():
    if os.path.exists(CONFIG_PATH) or not os.path.exists(LEGACY_PATH):
        return
    print("No launcher_configs.json found. Migrating from model_profiles.json:")
    legacy = config.load(LEGACY_PATH)
    doc, report = config.migrate(legacy, DEFAULT_ROOT, DEFAULT_EXE)
    config.save(CONFIG_PATH, doc)
    for line in report:
        print(line)
    print()


def scan_models(model_root):
    found = glob.glob(os.path.join(model_root, "**", "*.gguf"), recursive=True)
    return sorted(f for f in found if "mmproj" not in os.path.basename(f).lower())


def vram_line():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.free", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return out.splitlines()[0] if out else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def launch(data, cfg, values):
    err = catalog.spec_error(values)
    if err:
        print(f"\n  cannot launch: {err}\n")
        return

    root = data["model_root"]
    model_path = config.resolve_path(cfg["model"], root)
    draft_path = (config.resolve_path(values["draft_model"], root)
                  if values.get("draft_model") else None)
    argv = [data["llama_server"]] + catalog.build_argv(
        values, model_path, cfg.get("alias") or cfg["name"], draft_path)

    host, port = values["host"], values["port"]
    owner = server.port_owner(port)
    if owner:
        pid, name = owner
        if "llama-server" not in name.lower():
            print(f"\n  port {port} is held by {name} (pid {pid}), not a "
                  f"llama-server. Change the port on row 3.\n")
            return
        if ask(f"  port {port} is held by llama-server (pid {pid}). "
               f"Stop it? [Y/n] ").strip().lower() in ("", "y"):
            # expect_name re-checks identity at kill time. The snapshot above is
            # as old as the user's pause at this prompt, and Windows recycles
            # pids - without this, a server that exited meanwhile could hand its
            # pid to something unrelated that we would then force-kill.
            if not server.kill(pid, expect_name=name):
                print(f"  pid {pid} is no longer {name} - not killing it. "
                      f"Re-check the port and try again.")
                return
            print(f"  stopped pid {pid}")
        else:
            return

    print(f"\n  starting {cfg['name']} ...")
    proc = server.spawn(argv)
    ok, msg = server.wait_ready(host, port, proc, tick=lambda: print(".", end="",
                                                                    flush=True))
    print()
    print(f"  -> {msg}  (pid {proc.pid})" if ok else f"  FAILED: {msg}")


def run_board(data, cfg):
    values = config.resolve_values(data, cfg)
    dirty = set()
    root = data["model_root"]
    header = (f"{cfg['name']}\nModel: {os.path.basename(cfg['model'])}"
              f"   |  {vram_line()}")

    while True:
        print("\n" + board.render_board(values, dirty, header))
        action = board.dispatch(ask("> "))

        if action == "quit":
            return
        if action == "launch":
            launch(data, cfg, values)
            return
        if action == "command":
            model_path = config.resolve_path(cfg["model"], root)
            draft = (config.resolve_path(values["draft_model"], root)
                     if values.get("draft_model") else None)
            argv = [data["llama_server"]] + catalog.build_argv(
                values, model_path, cfg.get("alias") or cfg["name"], draft)
            print("\n" + subprocess.list2cmdline(argv) + "\n")
            continue
        if action == "save":
            cfg["settings"] = config.diff_from_defaults(data, values)
            config.save(CONFIG_PATH, data)
            dirty.clear()
            print(f"  saved to {os.path.basename(CONFIG_PATH)}")
            continue
        if action.startswith("edit:"):
            group = catalog.GROUPS[int(action.split(":")[1]) - 1]
            before = dict(values)
            values = board.edit_group(group, values, ask, print)
            if values != before:
                dirty.add(group.key)
            continue
        print("  unknown option")


def new_config(data):
    models = scan_models(data["model_root"])
    if not models:
        print("  no .gguf files found under", data["model_root"])
        return None
    for i, path in enumerate(models, 1):
        print(f"  {i:>2}  {os.path.relpath(path, data['model_root'])}")
    try:
        chosen = models[int(ask("\n  model number: ").strip()) - 1]
    except (ValueError, IndexError):
        print("  invalid selection")
        return None
    name = ask("  config name: ").strip()
    if not name:
        return None
    if any(c["name"] == name for c in data["configs"]):
        print(f"  a config named {name!r} already exists")
        return None
    cfg = {"name": name, "alias": name,
           "model": config.relativise(chosen, data["model_root"]), "settings": {}}
    data["configs"].append(cfg)
    return cfg


def main():
    first_run_migration()
    try:
        data = config.load(CONFIG_PATH)
    except config.ConfigError as exc:
        print(exc)
        return 1

    if not os.path.exists(data["llama_server"]):
        print(f"llama-server not found at {data['llama_server']}\n"
              f"Fix the 'llama_server' path in {CONFIG_PATH}")
        return 1

    while True:
        root = data["model_root"]
        resolved = {c["name"]: config.resolve_path(c["model"], root)
                    for c in data["configs"]}
        missing = {n for n, p in resolved.items() if not os.path.exists(p)}
        sizes = {n: os.path.getsize(p) for n, p in resolved.items()
                 if n not in missing}
        print("\n" + board.render_menu(data["configs"], missing, sizes))
        choice = ask("> ").strip().lower()

        if choice == "q":
            return 0
        if choice == "n":
            cfg = new_config(data)
            if cfg:
                run_board(data, cfg)
            continue
        try:
            cfg = data["configs"][int(choice) - 1]
        except (ValueError, IndexError):
            print("  invalid selection")
            continue
        if cfg["name"] in missing:
            print(f"  {cfg['name']} cannot launch: model file is missing")
            continue
        run_board(data, cfg)


if __name__ == "__main__":
    sys.exit(main())
