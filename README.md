<div align="center">

# llama-server launcher

**An interactive board for [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server`.**
Pick a named configuration, adjust any setting on a numbered board, press <kbd>Enter</kbd> to launch.

[![CI](https://github.com/gabrieljakob/llama-server-launcher/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrieljakob/llama-server-launcher/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-555)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licence)

</div>

---

Hand-writing `llama-server` command lines gets old fast once you have several models — and a
single model often needs several *different* command lines: one with speculative decoding, one
without, one on a different port. This launcher makes each of those a named thing you can pick
from a list.

```
Available launch configs:

   1  qwen3.6                          Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf     20.8 GB
   2  qwen3.8                          Qwen3.8-27B-UD-Q3_K_XL.gguf         12.5 GB
   3  gemma4                           gemma-4-12b-it-Q4_0.gguf             6.3 GB
   4  gemma4dflash                     gemma-4-12b-it-Q4_0.gguf             6.3 GB
   5  qwen3.8-preserve-thinking-coding Qwen3.8-27B-UD-Q3_K_XL.gguf         12.5 GB

  [n] new config from a .gguf   [q] quit
> 5

qwen3.8-preserve-thinking-coding
Model: Qwen3.8-27B-UD-Q3_K_XL.gguf   |  CUDA0: NVIDIA GeForce RTX 4080 (16375 MiB, 15074 MiB free)

  1  context      32768
  2  gpu layers   99
  3  host:port    127.0.0.1:8080
  4  sampling     temp 0.6  top-k 20  top-p 0.95  min-p 0.0
  5  penalties    presence -  frequency -  repeat -  repeat-last-n -
  6  reasoning    reasoning on  effort xhigh  preserve -  budget -  budget-message -
  7  toggles      jinja on  no-mmproj on  metrics off  fa on  kv-unified on
  8  kv cache     K f16 / V f16
  9  batching     -np auto  -b 2048  -ub 512
 10  speculative  draft-mtp  draft ngl auto  n-max 3  n-min 0  p-min 0.75
 11  template     preserve_thinking=true
 12  extra args   (none)

  [1-12] edit   [s] save   [c] show command   [Enter] launch   [q] back
```

## Contents

- [Highlights](#highlights) · [Requirements](#requirements) · [Quick start](#quick-start)
- [The board](#the-board) · [Configuration](#configuration) · [Reasoning](#reasoning) · [Speculative decoding](#speculative-decoding)
- [Launching](#launching) · [Tests](#tests) · [Layout](#layout)
- [Windows and locale notes](#windows-and-locale-notes)

## Highlights

| | |
|---|---|
| **One-line install** | One command on Windows, Linux or macOS. It brings its own Python, so you need neither Python nor git first. |
| **One model, many configs** | Configs are named command lines, not models. The same weights can appear five times with different flags. |
| **Backend-agnostic** | Asks the binary what devices it has instead of assuming a vendor — CUDA, ROCm, Vulkan, Metal or plain CPU. |
| **Nothing hardcoded** | Two paths, asked once on first run, kept in your per-user config folder and editable in JSON forever after. |
| **Unset means unset** | A setting shown as `-` is not passed at all, so `llama-server`'s own default applies. |
| **Speculative decoding, gated** | The `--spec-type` families need different arguments — one requires a draft model, one merely accepts it, one ignores it. The board adapts and validates before launching. |
| **Safe port takeover** | Offers to stop what owns the port *only* if it is your llama-server, and re-checks its name, its start time and the port at the moment it stops it. |
| **Real readiness** | Polls until the port actually accepts a connection. It does not claim the server started until something answers. |

## Requirements

- Windows, Linux or macOS
- Any `llama-server` build and some `.gguf` files

The installer brings [uv](https://docs.astral.sh/uv/), and uv brings Python 3.12+ and the two
libraries the launcher uses, [psutil](https://github.com/giampaolo/psutil) and
[platformdirs](https://github.com/tox-dev/platformdirs). psutil ships prebuilt for x86-64 and
arm64 on all three systems; on anything else uv needs a C compiler to build it.

Works with whatever backend your llama.cpp was built against. The launcher asks the binary what
devices it has rather than assuming a vendor, so an AMD card with a Vulkan build reports Vulkan,
and a CPU-only build says so.

## Quick start

**Windows**, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 | iex
```

**Linux and macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh | sh
```

Then:

```bash
llama-launcher
```

The installer needs no administrator rights. It installs uv if you do not have it, then installs
the latest release as a uv tool. Run the same line again to update, and
`uv tool uninstall llama-launcher` to remove it. Your config is not touched by any of the three.

<details>
<summary><b>Rather read the script before you run it?</b></summary>

<br>

Both are short. Download, read, then run:

```powershell
irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 -OutFile install.ps1
notepad install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

```bash
curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh -o install.sh
less install.sh
sh install.sh
```

</details>

From a clone instead:

```bash
git clone https://github.com/gabrieljakob/llama-server-launcher.git
cd llama-server-launcher
uv run llama-launcher
```

On Windows you can also double-click `launch_model.bat` in the clone.

On first run it asks for two paths and stores them in your config file:

```
Setting up. Two paths are needed; both are stored in
C:\Users\you\AppData\Roaming\llama-launcher\launcher_configs.json
and can be edited there later.

  llama-server executable [C:\llama.cpp\llama-server.exe]:
  folder containing your .gguf models: D:\models
```

Both are pre-filled where possible — `llama-server` is looked up on `PATH` and in the usual build
locations, and if you have a legacy `model_profiles.json` the model folder is derived from the
paths already in it. Press <kbd>Enter</kbd> to accept a suggestion.

Then press <kbd>n</kbd> to build a config from any `.gguf` it finds.

## The board

| Key | Does |
|:---:|---|
| <kbd>1</kbd>–<kbd>12</kbd> | Edit that row. Blank keeps the current value; `-` clears a setting back to llama-server's own default |
| <kbd>s</kbd> | Save — writes only the values that differ from the defaults, so the `defaults` block stays live |
| <kbd>c</kbd> | Print the equivalent command line, quoted for the shell you are in — PowerShell on Windows, a POSIX shell on Linux and macOS |
| <kbd>Enter</kbd> | Launch |
| <kbd>q</kbd> | Back |

A `*` marks a row you have edited but not saved. Failed launches keep the board, so a busy port
does not cost you your edits.

Settings shown as `-` are **not passed at all** — llama-server applies its own default. That is
deliberate: pre-filling `repeat 1.0` and `frequency 0.0` would put numbers on screen that nobody
chose, and they are not even uniform (`0.0` disables presence and frequency, but `1.0` is what
disables repeat).

Every setting shows, dash and all. A flag we are not passing used to render as nothing, which
turned out to hide the setting from the one screen it can be changed from — `preserve` sat in the
catalog, editable and working, while the board never mentioned it existed.

## Configuration

Everything lives in one file, `launcher_configs.json`, in your per-user config folder:

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\llama-launcher\` |
| Linux | `~/.config/llama-launcher/` (or `$XDG_CONFIG_HOME/llama-launcher/`) |
| macOS | `~/Library/Application Support/llama-launcher/` |

`llama-launcher --config PATH` uses a different file. If you ran the launcher from a clone before
0.1.0, the `launcher_configs.json` beside the code is copied to that folder the first time you
start it, and the original is left where it was.

It looks like this:

```json
{
  "version": 2,
  "model_root":   "D:/LLM Models",
  "llama_server": "D:/llama.cpp/llama-server.exe",

  "defaults": { "gpu_layers": "auto", "host": "127.0.0.1", "port": 8080,
                "temp": 0.6, "top_k": 20, "top_p": 0.95, "min_p": 0.0,
                "flash_attn": "on", "jinja": true, "no_mmproj": true,
                "cache_type_k": "f16", "cache_type_v": "f16" },

  "configs": [
    { "name": "qwen3.8-preserve-thinking-coding",
      "model": "Qwen3.8-27b/Qwen3.8-27B-UD-Q3_K_XL.gguf",
      "alias": "qwen3.8",
      "settings": {
        "context": 32768, "temp": 0.6,
        "reasoning": "on", "reasoning_effort": "xhigh", "kv_unified": "on",
        "spec_type": "draft-mtp", "spec_n_max": 3, "spec_p_min": 0.75,
        "chat_template_kwargs": { "preserve_thinking": true }
      } }
  ]
}
```

Values resolve in four layers, later winning:

```
catalog default  ->  file "defaults"  ->  the config's "settings"  ->  unsaved board edits
```

Model paths are relative to `model_root`; absolute paths work too. Saving is atomic — a temp file
plus `os.replace` — so an interrupted write cannot leave you with a truncated config.

> **One model, several configs.** `gemma4` and `gemma4dflash` above point at the same weights with
> different flags. That is the whole point of naming configs rather than listing models.

## Reasoning

Row 6 carries every `--reasoning*` flag, because they are one concept and the toggles row was
already the widest on the board:

| Shown | Flag | Unset means |
|---|---|---|
| `reasoning on \| off \| auto` | `--reasoning` | — (`auto` detects from the template) |
| `effort <level>` | `--reasoning-effort` | — (`default` keeps the template's own) |
| `preserve on \| off \| -` | `--reasoning-preserve` / `--no-reasoning-preserve` | the template decides |
| `budget <n> \| -` | `--reasoning-budget` | unrestricted (`-1`); `0` ends thinking immediately |
| `budget-message "<text>"` | `--reasoning-budget-message` | nothing is injected |

`budget-message` is free text, injected just before the end-of-thinking tag when the budget runs
out — so it only ever does anything alongside a `budget`. It is one argument however many spaces it
contains, on the board (where it is quoted, since rows separate values with two spaces), in the
`[c]` command line, and on the way to the process.

`preserve` is the one to reach for when llama-server announces at startup that the model's template
advertises the `supports_preserve_reasoning` capability — it keeps the reasoning trace for the whole
history rather than the last assistant message only. It is a **server-level** setting and only bites
on templates that advertise that capability.

`chat_template_kwargs.preserve_thinking` on row 11 is a *different* lever: that one is passed
through to the jinja template itself. The `qwen3.8-preserve-thinking-coding` config uses the kwarg.
If thinking still is not preserved in practice, `preserve on` is the second lever to try — the two
are not alternatives so much as two places the same wish can be expressed.

## Speculative decoding

The one part with real logic behind it. The `--spec-type` families do not all want the same
things, and the draft model is not a plain yes/no:

| `spec_type` | Draft model | Emits |
|---|:---:|---|
| `none` | — | nothing |
| `draft-simple`, `draft-eagle3`, `draft-dflash`, `draft-dspark` | **required** | `--spec-type`, `--spec-draft-model`, `--spec-draft-ngl`, shared knobs |
| `draft-mtp` | **optional** | `--spec-type`, shared knobs, plus `--spec-draft-model` and `--spec-draft-ngl` once a path is set |
| `ngram-*` | not used | `--spec-type`, shared knobs |

The draft-model row is always offered and never demanded. Set a path and
it is sent, and checked for existence before launch; leave it blank and no flag is emitted.

The launcher validates the required types before launching rather than letting the server fail,
and the speculative row adapts as you change the type — switching to an `ngram-*` type clears a
draft model that can no longer be used, and says so rather than dropping it silently.

Draft models never appear in the config menu. A `.gguf` that is a draft model is a *property* of a
config, not a launchable thing.

## Launching

The launcher checks what owns the target port and offers to stop it **only if it is your
llama-server** — the process name has to equal the file name of the binary in your config, not
merely contain it. Before it stops anything it re-checks three things: the name, the port, and the
moment the process was started. A port snapshot can be minutes old by the time you answer, and
operating systems recycle PIDs; a different process that inherited the PID has a different start
time and is left alone. Servers on other ports are never touched, so `:8080` and `:8082` coexist.

Stopping asks first: the server gets five seconds to shut down before it is forced.

On Windows the server starts in its own console window. On Linux and macOS it starts detached,
with its output in a log file whose path is printed — under `~/.local/state/llama-launcher/log/`
on Linux and `~/Library/Logs/llama-launcher/` on macOS. There is one file per config and port,
overwritten at each launch.

After spawning, the launcher polls until the port actually accepts a connection, watching for the
child exiting, and reports one of three outcomes: the URL, the exit code, or a timeout.

## Tests

```bash
uv run python -m unittest discover -s tests -t . -v
```

Every push runs them on Windows, Linux and macOS, on Python 3.12 and 3.14, together with both
install scripts. Most of the process layer is tested against a fake; `tests/test_server_live.py`
then starts a real process on each OS and finds it, refuses to stop it under the wrong identity,
and stops it under the right one.

<details>
<summary><b>How these tests earned their place</b></summary>

<br>

I wrote them under one rule: **a passing suite is weak evidence.**

Nine times while building this I found a test that could not fail. It asserted the outcome I
expected instead of the mechanism the behaviour actually depended on. I caught every one of them
by breaking the source on purpose and watching whether anything complained. Reading the tests
never caught a single one.

I ran roughly 800 of those mutations against this code. The tests still here are the ones that
failed when I took their behaviour away.

</details>

## Layout

```
install.ps1     Windows bootstrap
install.sh      Linux and macOS bootstrap
llama_launcher/
  catalog.py    setting definitions, validation, argv emission, speculative gating
  config.py     load/save, four-layer resolution, migration, atomic writes
  server.py     port ownership, guarded stop, spawn, readiness polling
  board.py      config menu, settings board, row editors, shell quoting
  __main__.py   entry point; wiring only
tests/
docs/           design specs and implementation plans
```

`catalog` and `config` are pure. `server` is the only module that touches processes.

Adding a new llama-server flag is **one record in `catalog.py`**. The consumers iterate the
catalog generically, and I know that holds because I added one and nothing else needed touching.

## Windows and locale notes

<details>
<summary><b>Three things I learned the hard way on a non-English Windows</b></summary>

<br>

- Console output is cp1252. Strings the launcher authors are ASCII; model names and paths are user
  data and pass through verbatim, with stdout widened to UTF-8 rather than mangling a filename.

- On Windows the extra-args row splits by **Windows** rules, not POSIX — `shlex.split` treats
  backslash as an escape and quietly turns `D:\LLM Models\x.gguf` into two mangled fragments. On
  Linux and macOS it uses POSIX rules, because there that is what you would type in a shell.

- On Windows `[c]` quotes for PowerShell, which needs different escaping from `cmd.exe` for the
  same argument. Launching is unaffected either way: arguments are passed as a list and never
  built into a command string.

</details>

## Licence

[MIT](LICENSE) — do what you like, keep the notice.
