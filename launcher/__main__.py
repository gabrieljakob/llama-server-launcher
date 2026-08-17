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


class Abort(Exception):
    """Raised by ask() when stdin ends or the user interrupts."""


def ask(prompt=""):
    """input() that turns EOF and Ctrl-C into an Abort instead of a traceback.

    A piped, redirected or closed stdin makes input() raise EOFError, and Ctrl-C
    raises KeyboardInterrupt. Either would end the session with a stack trace.

    This raises rather than returning a sentinel STRING, and that matters. A
    sentinel like "q" cannot be told apart from the user typing "q", which broke
    two ways: at the new-config name prompt an interrupt would silently create a
    config literally named "q", which any later save would persist; and in any
    row editor that re-prompts on invalid input, the sentinel fails validation,
    the loop asks again, and a closed stdin yields the sentinel forever - an
    infinite loop instead of the clean exit this function exists to provide.
    An exception cannot be mistaken for input, and cannot be re-prompted past."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise Abort from None


def first_run_migration():
    """Returns False if migration was needed but could not be done."""
    if os.path.exists(CONFIG_PATH) or not os.path.exists(LEGACY_PATH):
        return True
    print("No launcher_configs.json found. Migrating from model_profiles.json:")
    try:
        legacy = config.load(LEGACY_PATH)
    except config.ConfigError as exc:
        # A corrupt legacy file must report itself, not traceback. This is the
        # one load main() does not already guard.
        print(f"  cannot migrate: {exc}")
        print(f"  Fix {LEGACY_PATH}, or move it aside to start from scratch.")
        return False
    doc, report = config.migrate(legacy, DEFAULT_ROOT, DEFAULT_EXE)
    config.save(CONFIG_PATH, doc)
    for line in report:
        print(line)
    print()
    return True


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
    # Re-checked here, not only at the menu: the file may have moved between
    # rendering that list and pressing Enter. Failing here says why; failing
    # inside spawn does not.
    if not os.path.exists(model_path):
        print(f"\n  cannot launch: model file is gone - {model_path}\n")
        return
    draft_path = (config.resolve_path(values["draft_model"], root)
                  if values.get("draft_model") else None)
    if draft_path and not os.path.exists(draft_path):
        print(f"\n  cannot launch: draft model is gone - {draft_path}\n")
        return
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
    try:
        return _main()
    except Abort:
        # Ctrl-C or a closed stdin, from any depth. Quitting is the honest
        # response: nothing unsaved is written, and the alternative is guessing
        # which prompt the user meant to escape.
        print("  quit")
        return 0


def _main():
    if not first_run_migration():
        return 1
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
