"""Entry point. Wiring only - the logic lives in the other four modules."""
import glob
import os
import socket
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


def load_config(path):
    """config.load, with the one failure it does not wrap turned into the
    ConfigError every caller here already handles.

    load() converts the file-level failures it knows about - missing, locked,
    not UTF-8, not JSON. A document nested thousands of brackets deep is none of
    those: it is valid JSON that json.load gives up on with a RecursionError,
    which is neither a ValueError nor an OSError and so escaped both of its
    guards, straight out of the startup path as a traceback. A hand-edited file
    is exactly where that shape comes from."""
    try:
        return config.load(path)
    except RecursionError:
        raise config.ConfigError(
            f"{path} is nested too deeply to read - it is valid JSON, but with "
            f"thousands of nested brackets. The file was not modified.") from None


def save_config(path, data):
    """config.save, with the failures it does not wrap turned into ConfigError.

    save() promises one exception type and delivers it for the write itself, but
    its own cleanup - deleting the scratch file after a failed write - is
    unguarded, so a scratch file that cannot be removed replaces the ConfigError
    with a raw OSError. Every caller of this module's save is holding the user's
    unsaved edits, and a traceback out of it destroys them."""
    try:
        config.save(path, data)
    except config.ConfigError:
        raise
    except (OSError, RecursionError) as exc:
        raise config.ConfigError(f"could not write {path}: {exc}") from None


def first_run_migration():
    """Returns False if migration was needed but could not be done."""
    if os.path.exists(CONFIG_PATH) or not os.path.exists(LEGACY_PATH):
        return True
    print("No launcher_configs.json found. Migrating from model_profiles.json:")
    try:
        legacy = load_config(LEGACY_PATH)
    except config.ConfigError as exc:
        # A corrupt legacy file must report itself, not traceback. This is the
        # one load main() does not already guard.
        print(f"  cannot migrate: {exc}")
        print(f"  Fix {LEGACY_PATH}, or move it aside to start from scratch.")
        return False
    doc, report = config.migrate(legacy, DEFAULT_ROOT, DEFAULT_EXE)
    try:
        save_config(CONFIG_PATH, doc)
    except config.ConfigError as exc:
        print(f"  {exc}")
        print(f"  Nothing was migrated. {LEGACY_PATH} is untouched.")
        return False
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


def alias_of(cfg):
    """The --alias value for a config, as a string.

    str(), because a hand-edited "alias": 5 is a number, and a number in argv is
    a TypeError from inside Popen - which spawn() does not turn into a report,
    because it is not an OSError. Coercing once here keeps both the launch and
    the [c] command total, the way catalog.spec_types_of does for its row."""
    return str(cfg.get("alias") or cfg["name"])


def host_error(host, port):
    """Why the readiness probe could never reach `host`, or None if it can.

    Checked beside the port, and for the same reason. This value comes out of a
    file the user hand-edits, and the first thing that would have noticed a bad
    one is server.wait_ready - which runs AFTER llama-server is up. A host that
    is a number, or a name with a typo in it, therefore cost an orphaned server
    in a console window nobody asked for, plus the board and every unsaved edit
    on it. Refusing before anything starts costs a name lookup that is free for
    the 127.0.0.1 this is set to in practice.

    AF_INET, because that is the family server.port_open probes with. An
    IPv6-only host such as ::1 is a real llama-server bind address and a real
    dead end here: the server would come up and the probe could never see it,
    so it is refused with a message rather than waited on for five minutes."""
    if not isinstance(host, str) or not host.strip():
        return f"host {host!r} is not a hostname"
    try:
        socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except UnicodeError as exc:
        # NOT an OSError, so the clause below never caught it: UnicodeError is a
        # ValueError. getaddrinfo encodes the name with the idna codec BEFORE it
        # looks anything up, and that codec rejects some names outright - a DNS
        # label over 63 characters ('a'*64 is the exact threshold, fewer when
        # the name is non-ASCII, since idna encodes before measuring), a name
        # with an empty label such as a lone ".", or a character it cannot
        # encode at all. Every one of those is a plausible hand edit, and every
        # one left here as a traceback through main(), which catches only Abort
        # - killing the board and every unsaved edit on it. That is precisely
        # the outcome this function exists to prevent, so an unusable name is
        # reported like any other host that cannot be reached.
        return f"host {host!r} is not a usable hostname ({exc})"
    except OSError as exc:
        return f"host {host!r} cannot be reached over IPv4 ({exc})"
    return None


def launch(data, cfg, values):
    """Returns True only if a server is actually up. Every failure path returns
    False so run_board can keep the board - and the user's unsaved edits - up."""
    err = catalog.spec_error(values)
    if err:
        print(f"\n  cannot launch: {err}\n")
        return False

    # Read and check the port BEFORE anything is started. A hand-edited config
    # can hold "8080" as a string, which emits fine as an argument but is a
    # TypeError inside socket.connect_ex - raised from wait_ready, after the
    # server is already running, with no way back to the board.
    port = values.get("port")
    try:
        port = int(port)
    except (TypeError, ValueError):
        print(f"\n  cannot launch: port {port} is not a whole number "
              f"- fix it on row 3.\n")
        return False
    host = values.get("host")
    bad_host = host_error(host, port)
    if bad_host:
        print(f"\n  cannot launch: {bad_host} - fix it on row 3.\n")
        return False

    root = data["model_root"]
    model_path = config.resolve_path(cfg["model"], root)
    # Re-checked here, not only at the menu: the file may have moved between
    # rendering that list and pressing Enter. Failing here says why; failing
    # inside spawn does not.
    if not os.path.exists(model_path):
        print(f"\n  cannot launch: model file is gone - {model_path}\n")
        return False
    # Gated on active_keys, the same question build_argv asks before it emits.
    # A draft_model left behind on a config whose spec type does not use one -
    # draft-mtp, and every ngram-* type - is not a launch blocker: build_argv
    # omits --spec-draft-model entirely for those, so checking the file refused
    # the launch over a path that was never going to be sent. The value stays on
    # the board and in the file, ready for the type that does use it.
    draft_live = "draft_model" in catalog.active_keys(values)
    draft_path = (config.resolve_path(str(values["draft_model"]), root)
                  if draft_live and values.get("draft_model") else None)
    if draft_path and not os.path.exists(draft_path):
        print(f"\n  cannot launch: draft model is gone - {draft_path}\n")
        return False
    argv = [data["llama_server"]] + catalog.build_argv(
        values, model_path, alias_of(cfg), draft_path)

    owner = server.port_owner(port)
    if owner and owner[0] is None:
        # port_owner's third answer: netstat could not be asked, so the port's
        # state is unknown. Not evidence that it is busy, and not evidence that
        # it is free - saying "held by unknown (pid None)" would be neither.
        # Going on is the honest choice: llama-server refuses to start on a
        # taken port, and wait_ready reports that as an exit code.
        print(f"  could not check whether port {port} is free - starting anyway")
        owner = None
    if owner:
        pid, name = owner
        # Exact image name, not a substring: "llama-server-proxy.exe" contains
        # "llama-server" and would have been offered up for a force-kill as
        # though it were ours. tasklist reports the image name alone, so an
        # equality test is the whole identity we have.
        if name.lower() != "llama-server.exe":
            print(f"\n  port {port} is held by {name} (pid {pid}), not a "
                  f"llama-server. Change the port on row 3.\n")
            return False
        if ask(f"  port {port} is held by llama-server (pid {pid}). "
               f"Stop it? [Y/n] ").strip().lower() in ("", "y"):
            # expect_name re-checks identity at kill time. The snapshot above is
            # as old as the user's pause at this prompt, and Windows recycles
            # pids - without this, a server that exited meanwhile could hand its
            # pid to something unrelated that we would then force-kill.
            if not server.kill(pid, expect_name=name):
                print(f"  pid {pid} is no longer {name} - not killing it. "
                      f"Re-check the port and try again.")
                return False
            print(f"  stopped pid {pid}")
        else:
            return False

    print(f"\n  starting {cfg['name']} ...")
    proc = server.spawn(argv)
    if proc is None:
        # spawn() reports a start it could not make by returning None instead of
        # raising - the exe having been moved, renamed or deleted mid-session is
        # an ordinary outcome, and it used to arrive here as an OSError
        # traceback. Said here rather than left to wait_ready, because there is
        # no readiness to wait for and the path that is wrong is worth naming.
        print(f"\n  FAILED: llama-server could not be started from "
              f"{data['llama_server']}\n  Check that path - the file may have "
              f"been moved or renamed.\n")
        return False
    ok, msg = server.wait_ready(host, port, proc, tick=lambda: print(".", end="",
                                                                    flush=True))
    print()
    print(f"  -> {msg}  (pid {proc.pid})" if ok else f"  FAILED: {msg}")
    return ok


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
            # Only leave the board on success. Returning unconditionally threw
            # away every unsaved edit the moment a port was busy or a file had
            # moved - the user retypes their work to find out why it failed.
            if launch(data, cfg, values):
                return
            continue
        if action == "command":
            # Same gate as launch. Without it [c] printed a command line that
            # llama-server rejects, and the user - who asked precisely because
            # they wanted to check it - had no way to tell it was invalid.
            err = catalog.spec_error(values)
            if err:
                print(f"\n  no command to show: {err}\n")
                continue
            model_path = config.resolve_path(cfg["model"], root)
            draft = (config.resolve_path(str(values["draft_model"]), root)
                     if values.get("draft_model") else None)
            argv = [data["llama_server"]] + catalog.build_argv(
                values, model_path, alias_of(cfg), draft)
            print("\n" + board.as_powershell(argv) + "\n")
            continue
        if action == "save":
            # Settings this launcher has no catalog entry for are the user's
            # own: hand-added for a flag we do not model yet. diff_from_defaults
            # returns catalog keys and nothing else, so writing its result
            # straight back DELETED those lines from the file, silently, on the
            # next [s]. They are carried across instead, and said out loud -
            # nothing on the board shows them, so a user who is not told would
            # have no way to know they are still there.
            known = set(catalog.catalog_defaults())
            before = cfg.get("settings")
            kept = ({k: v for k, v in before.items() if k not in known}
                    if isinstance(before, dict) else {})
            cfg["settings"] = {**kept, **config.diff_from_defaults(data, values)}
            appended = False
            if not any(c is cfg for c in data["configs"]):
                # A config made with [n] joins the document only when it is
                # actually saved - the spec says "written on [s]". Appending it
                # at creation meant an unrelated later save persisted a config
                # the user had opened and walked away from. Identity, not
                # equality: two configs can compare equal.
                data["configs"].append(cfg)
                appended = True
            try:
                save_config(CONFIG_PATH, data)
            except config.ConfigError as exc:
                # Report and stay on the board. The edits are still in `values`,
                # and a traceback out of here would destroy exactly the work
                # the user pressed [s] to keep.
                #
                # And put the document back as it was, because nothing here was
                # written: the append and the new settings are in memory, and a
                # LATER save - of another config entirely - would write them
                # out. That is the same abandoned-config bug the append was
                # moved here to fix, just reached through a failed save.
                if appended:
                    for i, c in enumerate(data["configs"]):
                        if c is cfg:
                            del data["configs"][i]
                            break
                if before is None:
                    cfg.pop("settings", None)
                else:
                    cfg["settings"] = before
                print(f"  {exc}")
                continue
            dirty.clear()
            print(f"  saved to {os.path.basename(CONFIG_PATH)}")
            if kept:
                print(f"  kept {len(kept)} setting(s) this launcher does not "
                      f"know: {', '.join(sorted(kept))}")
                print(f"    they are saved unchanged, and are NOT passed to "
                      f"llama-server")
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
        index = int(ask("\n  model number: ").strip())
    except ValueError:
        print("  invalid selection")
        return None
    # Explicit lower bound: Python indexes from the end for 0 and negatives, so
    # "0" silently picked the LAST scanned file - which on this disk is a draft
    # model, not something you can launch.
    if not 1 <= index <= len(models):
        print("  invalid selection")
        return None
    chosen = models[index - 1]

    name = ask("  config name: ").strip()
    if not name:
        return None
    if any(c["name"] == name for c in data["configs"]):
        print(f"  a config named {name!r} already exists")
        return None
    return {"name": name, "alias": name,
            "model": config.relativise(chosen, data["model_root"]), "settings": {}}


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
        data = load_config(CONFIG_PATH)
    except config.ConfigError as exc:
        print(exc)
        return 1

    # Shape before use. Valid JSON is not a valid document: a deleted key or a
    # config without a name used to surface as a KeyError from whichever line
    # happened to read it first, naming nothing the user could act on.
    shape = config.document_error(data, CONFIG_PATH)
    if shape:
        print(shape)
        print("Fix that file, or move it aside to start from scratch.")
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
            index = int(choice)
        except ValueError:
            print("  invalid selection")
            continue
        # Explicit lower bound: Python indexes from the end for 0 and negatives,
        # so "0" silently opened the LAST config and "-1" the second-to-last.
        if not 1 <= index <= len(data["configs"]):
            print("  invalid selection")
            continue
        cfg = data["configs"][index - 1]
        if cfg["name"] in missing:
            print(f"  {cfg['name']} cannot launch: model file is missing")
            continue
        run_board(data, cfg)


if __name__ == "__main__":
    sys.exit(main())
