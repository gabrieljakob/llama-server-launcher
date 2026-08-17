<div align="center">

# llama-server launcher

**An interactive board for [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server`.**
Pick a named configuration, adjust any setting on a numbered board, press <kbd>Enter</kbd> to launch.

[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-success)](#requirements)
[![Tests](https://img.shields.io/badge/tests-377%20passing-brightgreen)](#tests)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)](#porting)
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
  6  toggles      jinja on  no-mmproj on  reasoning on  effort xhigh  fa on  kv-unified on
  7  kv cache     K f16 / V f16
  8  batching     -np auto  -b 2048  -ub 512
  9  speculative  draft-mtp  draft ngl auto  n-max 3  n-min 0  p-min 0.75
 10  template     preserve_thinking=true
 11  extra args   (none)

  [1-11] edit   [s] save   [c] show command   [Enter] launch   [q] back
```

## Contents

- [Highlights](#highlights) · [Requirements](#requirements) · [Quick start](#quick-start)
- [The board](#the-board) · [Configuration](#configuration) · [Speculative decoding](#speculative-decoding)
- [Launching](#launching) · [Tests](#tests) · [Layout](#layout)
- [Porting](#porting) · [Windows and locale notes](#windows-and-locale-notes)

## Highlights

| | |
|---|---|
| **Zero install** | Python 3.12 standard library only. No venv, no `pip`, no lockfile. |
| **One model, many configs** | Configs are named command lines, not models. The same weights can appear five times with different flags. |
| **Backend-agnostic** | Asks the binary what devices it has instead of assuming a vendor — CUDA, ROCm, Vulkan, Metal or plain CPU. |
| **Nothing hardcoded** | Two paths, asked once on first run, editable in JSON forever after. |
| **Unset means unset** | A setting shown as `-` is not passed at all, so `llama-server`'s own default applies. |
| **Speculative decoding, gated** | The `--spec-type` families need different arguments — one requires a draft model, one merely accepts it, one ignores it. The board adapts and validates before launching. |
| **Safe port takeover** | Offers to stop what owns the port *only* if it is a llama-server, re-verifying identity immediately before the kill. |
| **Real readiness** | Polls until the port actually accepts a connection. It does not claim the server started until something answers. |

## Requirements

- **Python 3.12+** — standard library only, nothing to install
- Any `llama-server` build and some `.gguf` files

Works with whatever backend your llama.cpp was built against. The launcher asks the binary what
devices it has rather than assuming a vendor, so an AMD card with a Vulkan build reports Vulkan,
and a CPU-only build says so.

> [!NOTE]
> **Currently Windows-only**, because the port/process layer shells out to `netstat`, `tasklist`
> and `taskkill`. Everything else is portable — see [Porting](#porting).

## Quick start

```bash
git clone https://github.com/gabrieljakob/llama-server-launcher.git
cd llama-server-launcher
python -m launcher
```

Or double-click `launch_model.bat`.

On first run it asks for two paths and stores them in `launcher_configs.json`:

```
Setting up. Two paths are needed; both are stored in
launcher_configs.json and can be edited there later.

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
| <kbd>1</kbd>–<kbd>11</kbd> | Edit that row. Blank keeps the current value; `-` clears a setting back to llama-server's own default |
| <kbd>s</kbd> | Save — writes only the values that differ from the defaults, so the `defaults` block stays live |
| <kbd>c</kbd> | Print the equivalent command line, quoted so it can be pasted into PowerShell |
| <kbd>Enter</kbd> | Launch |
| <kbd>q</kbd> | Back |

A `*` marks a row you have edited but not saved. Failed launches keep the board, so a busy port
does not cost you your edits.

Settings shown as `-` are **not passed at all** — llama-server applies its own default. That is
deliberate: pre-filling `repeat 1.0` and `frequency 0.0` would put numbers on screen that nobody
chose, and they are not even uniform (`0.0` disables presence and frequency, but `1.0` is what
disables repeat).

## Configuration

Everything lives in `launcher_configs.json`:

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

The launcher checks what owns the target port and offers to stop it **only if it is a
llama-server**, re-verifying the process identity immediately before killing — a port snapshot can
be minutes old by the time you answer, and Windows recycles PIDs. Servers on other ports are left
alone, so `:8080` and `:8082` coexist.

After spawning, it polls until the port actually accepts a connection, watching for the child
exiting, and reports one of three outcomes: the URL, the exit code, or a timeout.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

**377 tests, standard library only.**

<details>
<summary><b>Why the count is not the point</b></summary>

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
launcher/
  catalog.py    setting definitions, validation, argv emission, speculative gating
  config.py     load/save, four-layer resolution, migration, atomic writes
  server.py     port ownership, targeted kill, spawn, readiness polling
  board.py      config menu, settings board, row editors, PowerShell quoting
  __main__.py   entry point; wiring only
tests/          377 tests
docs/           design spec and implementation plan
```

`catalog` and `config` are pure. `server` is the only module that touches processes.

Adding a new llama-server flag is **one record in `catalog.py`**. The consumers iterate the
catalog generically, and I know that holds because I added one and nothing else needed touching.

## Porting

The only OS-specific module is `server.py`, which finds what owns a TCP port and stops it. It
shells out to `netstat -ano`, `tasklist` and `taskkill`. A POSIX port means replacing those three
with `ss`/`lsof`, `ps` and `signal`, keeping the same four functions — the rest of the codebase
never touches a process. `spawn()` also asks for a new console window, which is a Windows flag
guarded by `sys.platform`.

Nothing else assumes an OS: paths go through `os.path`, the executable name already varies by
platform, and device detection asks the binary.

## Windows and locale notes

<details>
<summary><b>Five things I learned the hard way on a non-English Windows</b></summary>

<br>

- `netstat` and `tasklist` print **localised** output. Listening sockets are identified by row
  *shape* (a wildcard remote address), never by matching `LISTENING`, which reads `ABHÖREN` on a
  German install.

- `tasklist`'s "no such process" line is localised **and** exits 0, so only the absent CSV row
  distinguishes it. Its text also contains bytes that are undefined in cp1252, which crashed
  `subprocess` decoding in a reader thread where no `try` could see it — both console tools are
  read with the OEM codepage.

- Console output is cp1252. Strings the launcher authors are ASCII; model names and paths are user
  data and pass through verbatim, with stdout widened to UTF-8 rather than mangling a filename.

- The extra-args row splits by **Windows** rules, not POSIX — `shlex.split` treats backslash as an
  escape and quietly turns `D:\LLM Models\x.gguf` into two mangled fragments.

- `[c]` quotes for PowerShell, which needs different escaping from `cmd.exe` for the same argument.
  Launching is unaffected either way: arguments are passed as a list and never built into a command
  string.

</details>

## Licence

[MIT](LICENSE) — do what you like, keep the notice.
