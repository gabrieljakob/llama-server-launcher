# llama-server Launcher — Design

**Date:** 2026-08-17
**Status:** Approved, ready for implementation planning
**Supersedes:** `model_launcher.py` (flat, single-file), `LLAMA.bat` (hardcoded single model)

---

## 1. Context

The current `model_launcher.py` lists GGUF models and starts `llama-server.exe` with a
fixed flag set drawn from `model_profiles.json`. Three problems make it unfit for how the
models are actually run:

1. **The flag set is hardcoded.** Some launches need a dozen flags the launcher cannot
   emit — speculative decoding (`--spec-draft-model`, `--spec-type`, `--spec-draft-n-max`,
   `--spec-draft-ngl`), batching (`-np`, `-b`, `-ub`), `--reasoning`, `--metrics`.
2. **Flags vary per model.** `gemma-4-12b-it-Q4_0` runs with a DFlash draft model;
   Qwen3.6 has no draft model at all. A flat prompt list cannot express "this group of
   flags applies only to this model."
3. **Draft models are modelled as launchable models.** `gemma-4-12B-it-DFlash-Q8_0.gguf`
   and `dspark_gemma4_12b_q4pure.gguf` are draft models that pair with gemma4 via
   `draft-dflash` / `draft-dspark`. Both currently appear in the menu as standalone
   models, and `dspark` is a top-level entry in `model_profiles.json`.

A fourth, smaller issue: the launcher unconditionally `taskkill`s every `llama-server.exe`
before starting, which prevents running two models on two ports.

### Target environment

Facts verified against the installed binary on 2026-08-17. The design depends on these;
re-check them after a llama.cpp rebuild.

| | |
|---|---|
| Binary | `D:\llama.cpp\llama-server.exe`, build 10453, commit `3cb7ffb1a` |
| Devices | `CUDA0: NVIDIA GeForce RTX 4080 (16375 MiB)` — **only device; no Vulkan backend** |
| Python | 3.12.10 |
| Models | 8 launchable `.gguf` under `D:\LLM Models` (~80 GB), plus 3 `mmproj*` files |

Two models (Qwen3.6 at 20.8 GB, Ornith at 19.7 GB) exceed the 16 GB card, so `-ngl` is a
setting that must genuinely vary per config. Note that `-ngl` now accepts `auto` / `all` /
N and defaults to `auto`; the existing profiles' hardcoded `99` is the older idiom.

---

## 2. Goals and non-goals

**Goals**

- Expose the flags actually used, per launch, without editing Python.
- Represent one model appearing in several distinct launch configurations.
- Never present a draft model as a launchable model.
- Allow servers on different ports to coexist.
- Report launch success from observed state, not assumption.

**Non-goals**

- Auto-tuning `-ngl`, context, or KV cache from VRAM. The board *displays* model size
  against free VRAM; it never chooses for the user.
- Exposing every llama-server flag (~200). Out-of-catalog flags go through the raw
  extra-args row.
- Device/multi-GPU flags (`--device`, `--tensor-split`, `--main-gpu`, `--split-mode`).
  One device exists. Extra-args covers exotic cases.
- Draft KV cache types (`-ctkd`, `-ctvd`), `--reasoning-format`, `--reasoning-budget`.
  Extra-args covers these.

  **`--reasoning-effort` was promoted out of this list on 2026-08-17.** It was originally
  cut alongside the other reasoning flags. The user runs Qwen3.8-27B with reasoning effort
  enabled and wants `xhigh`, so it becomes a catalog row instead. Verified against build
  10453: the documented levels are `default, minimal, low, medium, high, xhigh, max`, and
  all parse. The value is passed through to the chat template, so whether a level is
  honoured depends on the model's template rather than on llama-server.
- Managing, downloading or converting model files.

---

## 3. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Interaction | **Settings board** — all rows visible, edit by number, Enter launches | Common case is launch-immediately; full control without a 12-prompt wizard every time |
| Flag scope | **Curated catalog + raw escape hatch** | Validates what it knows, never blocks what it doesn't |
| Menu unit | **Named launch configs** | One model, many configs; draft models become a property, not an entry |
| Kill policy | **Stop only the target port's owner** | 8080 and 8082 coexist; relaunching a config still just works |
| Structure | **Small package** (`launcher/`) | Distinct concerns; pure units testable without booting a UI |

---

## 4. Architecture

```
Scripts/
  launch_model.bat          -> python -m launcher
  launcher_configs.json     data (replaces model_profiles.json)
  model_profiles.json       left in place as rollback; read once for migration
  launcher/
    __main__.py             entry point, wiring only
    catalog.py              setting definitions, groups, argv emission
    config.py               load/save/merge, defaults layering, migration
    board.py                config menu + settings board UI
    server.py               port ownership, targeted kill, spawn, readiness
  tests/
    test_catalog.py  test_config.py  test_server.py  test_board.py
  docs/
    launcher-design.md      this file
```

Dependency direction is one-way: `__main__` → `board` → (`catalog`, `config`, `server`).
`catalog` and `config` import nothing from the others and are pure — no I/O beyond
`config`'s explicit file read/write. `server` is the only module that touches processes.

Standard library only. No pip installs.

---

## 5. The catalog

Two levels. **Settings** map 1:1 to llama-server flags. **Groups** are the numbered board
rows; a row may hold several settings.

Each setting declares: `key` (identity in JSON), `flag`, `label`, `type`, `default`,
`choices`, `validator`.

| Row | Setting keys | Flags | Type | Default |
|---|---|---|---|---|
| 1 context | `context` | `-c` | int > 0 | 8192 |
| 2 gpu layers | `gpu_layers` | `-ngl` | `auto` \| `all` \| int ≥ 0 | `auto` |
| 3 host:port | `host`, `port` | `--host`, `--port` | str, int 1–65535 | `127.0.0.1`, 8080 |
| 4 sampling | `temp`, `top_k`, `top_p`, `min_p` | `--temp`, `--top-k`, `--top-p`, `--min-p` | float ≥ 0, int ≥ 0, float 0–1, float 0–1 | 0.6, 20, 0.95, 0.0 |
| 5 penalties | `presence_penalty`, `frequency_penalty`, `repeat_penalty`, `repeat_last_n` | `--presence-penalty`, `--frequency-penalty`, `--repeat-penalty`, `--repeat-last-n` | float, float, float ≥ 0, int ≥ 0 | **all unset** |
| 6 reasoning | `reasoning`, `reasoning_effort`, `reasoning_preserve`, `reasoning_budget` | `-rea`, `--reasoning-effort`, `--reasoning-preserve`, `--reasoning-budget` | choice, choice, tri, int ≥ -1 | `auto`, `default`, unset, unset |
| 7 toggles | `jinja`, `no_mmproj`, `metrics`, `flash_attn`, `kv_unified` | `--jinja`, `--no-mmproj`, `--metrics`, `-fa`, `-kvu` | bool, bool, bool, choice, tri | true, true, false, `on`, unset |
| 8 kv cache | `cache_type_k`, `cache_type_v` | `-ctk`, `-ctv` | choice | `f16`, `f16` |
| 9 batching | `parallel`, `batch`, `ubatch` | `-np`, `-b`, `-ub` | int | -1 (auto), 2048, 512 |
| 10 speculative | `spec_type`, `draft_model`, `spec_ngl`, `spec_n_max`, `spec_n_min`, `spec_p_min` | `--spec-type`, `--spec-draft-model`, `--spec-draft-ngl`, `--spec-draft-n-max`, `--spec-draft-n-min`, `--spec-draft-p-min` | choice-list, path, str, int, int, float | `none`, none, `auto`, 3, 0, 0.0 |
| 11 template | `chat_template_kwargs` | `--chat-template-kwargs` | JSON object | `{}` |
| 12 extra args | `extra` | *(verbatim)* | str | `""` |

**The reasoning settings are their own row**, split out of toggles on 2026-08-17 when
`reasoning_budget` was added. Same argument as the penalties row: eight values on one line
stops being readable, and these four are one concept. Discoverability was the trigger —
build 10453 announces at startup that a model's template advertises
`supports_preserve_reasoning`, and the flag it is pointing at was in the catalog and
editable but invisible on the board (see the tri-state rendering note below), so the
apparent way to act on that log line was hand-editing row 11's template kwargs.

**The penalties row defaults to unset**, not to llama-server's values (`0.0 / 0.0 / 1.0 /
64`). Pre-filling them would put numbers on the board that nobody chose, and someone
unfamiliar with these samplers cannot tell a default from a decision. The pairing is not
even uniform — `0.0` disables presence and frequency, but `1.0` is what disables repeat —
so a pre-filled row would actively mislead about what "off" looks like. Unset renders as
`-`, emits no flag at all, and llama-server applies its own default. A number appears only
once someone sets one, and typing `-` sets it back.

That is the general rule for any setting whose catalog default is `None`: we do not pass
that flag. `draft_model` is the other one.

**Allowed values**, from `llama-server --help` on build 10453:

- `cache_type_k` / `cache_type_v`: `f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1`
- `spec_type`: comma-separated from `none, draft-simple, draft-eagle3, draft-mtp,
  draft-dflash, draft-dspark, ngram-simple, ngram-map-k, ngram-map-k4v, ngram-mod,
  ngram-cache`
- `reasoning`, `flash_attn`: `on, off, auto`
- `reasoning_effort`: `default, minimal, low, medium, high, xhigh, max`. Passed through to
  the chat template; llama-server does not validate it, so an unlisted value is accepted at
  the command line and simply ignored by a template that does not understand it.
- **tri** types are unset / on / off, emitting nothing / `--flag` / `--no-flag`
  respectively. `--kv-unified` and `--reasoning-preserve` both default to a value the
  binary decides (slot count and chat template respectively), so "unset" must stay
  distinct from "off" — a plain bool would silently override the binary's choice.
- `reasoning_budget` is `int ≥ -1`, not `int ≥ 0`: `-1` is unrestricted, `0` ends thinking
  immediately and `N > 0` is a token budget, so `-1` is the smallest value the flag has a
  meaning for. Build 10453 accepts `-2` without complaint, which would leave a typo to be
  discovered as strange model behaviour instead of as a message on the row it came from.
  The board renders `-1` as `budget unrestricted`, the same courtesy `-np -1` gets as
  `auto` — display only, emission still sends the number.
- **An unset setting renders as `label -`, for every type including tri.** Tri-states used
  to render as nothing at all, reasoned as "`off` would claim we pass `--no-flag` when we
  pass nothing". True of `off` and not of `-`, and the cost was the whole setting:
  `reasoning_preserve` shipped catalogued, editable and emitting, and the board never once
  said it existed. A setting the user cannot see is a setting the user cannot use.

### Emission rules

Type-driven, so adding a setting never means touching the command builder:

- **Valued types** (int, float, str, path, choice) emit `flag value` when the resolved
  value is not `None`.
- **Bool types** emit the bare flag when true, and emit *nothing* when false. `--metrics`
  off disappears rather than becoming `--metrics false`.
- **Tri types** emit nothing when unset, `--flag` when on, `--no-flag` when off.
- **The template row** is stored as a JSON object and emitted as a compact JSON *string*:
  `--chat-template-kwargs {"preserve_thinking":true}`. Storing it
  as an object keeps the config file readable and lets the board validate it as JSON
  before launch rather than after. Emitted only when non-empty.
- **The extra-args row** is `shlex.split` and appended last, so a user flag can override an earlier one.
- `--model` and `--alias` come from the config record itself, not the catalog.

### Speculative decoding gating

The speculative row is gated on **`spec_type`**, not on `draft_model`. The three families behave
differently and a single rule cannot cover them:

| `spec_type` | Draft model | Emits |
|---|---|---|
| `none` | — | nothing from row 10 |
| `draft-simple`, `draft-eagle3`, `draft-dflash`, `draft-dspark` | **required** | `--spec-type`, `--spec-draft-model`, `--spec-draft-ngl`, plus shared knobs |
| `draft-mtp` | **must not be set** — MTP is built into the model | `--spec-type`, plus shared knobs |
| `ngram-*` (5 types) | not used | `--spec-type`, plus shared knobs; family-specific `--spec-ngram-*` flags via extra-args |

Shared knobs are `--spec-draft-n-max`, `--spec-draft-n-min`, `--spec-draft-p-min`, emitted
for every non-`none` type.

Validation, checked before launch rather than left to the server: a draft-model type with
no `draft_model` set is an error naming the missing piece; `draft-mtp` with a `draft_model`
set is an error too, since the model provides its own draft path.

The twelve `--spec-ngram-*-size-n/-size-m/-min-hits/-n-match` flags are deliberately not
catalogued (see non-goals) — but the gating above must not *prevent* them, which is why
`spec_type` stays independently settable.

Adding a flag later (e.g. `--cache-reuse`) is one new record in `catalog.py`.

---

## 6. Config file and migration

`launcher_configs.json` replaces `model_profiles.json`. `MODEL_ROOT` and `LLAMA_SERVER`
move out of Python and into this file — relocating a drive no longer means editing code.

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
    { "name": "gemma4dflash",
      "model": "unsloth/gemma-4-12b-it-GGUF/gemma-4-12b-it-Q4_0.gguf",
      "alias": "gemma4dflash",
      "settings": {
        "context": 128000, "port": 8082, "gpu_layers": "99",
        "parallel": 1, "batch": 512, "ubatch": 128,
        "reasoning": "on", "metrics": true,
        "draft_model": "gemma4dflash/gemma4dflashmodel/gemma-4-12B-it-DFlash-Q8_0.gguf",
        "spec_type": "draft-dflash", "spec_n_max": 4, "spec_ngl": "99"
      } },

    { "name": "qwen3.8-preserve-thinking-coding",
      "model": "Qwen3.8-27b/Qwen3.8-27B-UD-Q3_K_XL.gguf",
      "alias": "qwen3.8",
      "settings": {
        "temp": 0.6, "presence_penalty": 0.0,
        "kv_unified": "on", "reasoning": "on", "reasoning_effort": "xhigh",
        "spec_type": "draft-mtp", "spec_n_max": 3, "spec_p_min": 0.75,
        "chat_template_kwargs": { "preserve_thinking": true }
      } }
  ]
}
```

The second config is the preserve-thinking-coding preset. Note the absence of
`draft_model`: `draft-mtp` uses the multi-token-prediction head built into the Qwen3.8
weights, so a separate draft GGUF would be an error (§5, gating table).

Model paths are stored **relative to `model_root`**; absolute paths are accepted and used
as-is (`os.path.isabs`). All path comparison goes through
`canon(p) = os.path.normcase(os.path.normpath(p))` — the fix already applied to the
separator/case bug in the current launcher.

### Value resolution

Four layers, later wins:

```
catalog default  →  file "defaults"  →  config "settings"  →  unsaved board edits
```

`[s]` writes into that config's `settings` block **only the values that differ from the
layer beneath** (catalog default overlaid with file `defaults`). Saving the fully resolved
set instead would copy all ~20 values into every config, and later edits to `defaults`
would silently stop reaching them. Config blocks stay minimal and `defaults` stays live.

Writes go through a temp file plus `os.replace`, so an interrupted save cannot truncate
the config file.

### Migration

Runs once, when `launcher_configs.json` is absent and `model_profiles.json` is present:

- `ngl` → `gpu_layers`; `flash_attn: true` → `"on"`; other keys carry across by name.
- Each `models[]` entry becomes a config keyed by its `alias` (falling back to `name`).
- Absolute model paths are relativised against `model_root`.
- **`model_profiles.json` is left untouched** as the rollback path.
- The migration prints a report, and flags `dspark` as probably a draft model rather than
  silently restructuring it. Keeping or deleting that config is a user decision.

---

## 7. Board behaviour

**Config menu** — lists configs from the file: name, model basename, file size. A config
whose model file is missing is listed and marked `!missing`, and cannot be launched.
`[q]` quits.

`[n]` builds a new config: pick a `.gguf` from the scan, then enter a name (rejected if it
collides with an existing config). `alias` defaults to the name. The board then opens on
catalog and file defaults, and the config is only written on `[s]`.

Scanning still walks `model_root` for `*.gguf` (skipping `mmproj*`), but scanned files
appear **only** under `[n]` and the speculative-row draft picker — never as menu entries. This is
what stops draft models masquerading as launchable models.

Row 10 edits `spec_type` first, then adapts: a `draft-*` type opens the `.gguf` picker for
`draft_model` and prompts `spec_ngl`; `draft-mtp` and the `ngram-*` types skip straight to
the shared knobs; `none` skips the rest entirely. The template row accepts a JSON object and
re-prompts on a parse error, so a malformed template kwarg is caught at edit time rather
than surfacing as a server startup failure.

**Settings board:**

```
qwen3.8-preserve-thinking-coding
Model: Qwen3.8-27B-UD-Q3_K_XL    12.5 GB   |  CUDA0: 15.0 GB free

  1  context      32768
  2  gpu layers   auto
  3  host:port    127.0.0.1:8080
  4  sampling     temp 0.6  top-k 20  top-p 0.95  min-p 0.0
  5  penalties    presence 0.0  frequency -  repeat -  repeat-last-n -
  6  reasoning    reasoning auto  effort xhigh  preserve -  budget -
  7  toggles      jinja on  no-mmproj on  metrics off  fa on  kv-unified on
  8  kv cache     K f16 / V f16
  9  batching     -np auto  -b 2048  -ub 512
*10  speculative  draft-mtp  (built-in, no draft model)  n-max 3  n-min 0  p-min 0.75
 11  template     preserve_thinking=true
 12  extra args   (none)

  [1-12] edit   [s] save   [c] show command   [Enter] launch   [q] back
```

- `*` marks rows edited but not yet saved.
- Row 10 shows every shared knob (`n-max`, `n-min`, `p-min`), and additionally `draft ngl`
  when the spec type takes a separate draft model. An earlier draft of this mockup omitted
  `n-min`, contradicting §5 which lists it as a real setting: a setting the user can edit
  must be one the user can see, so the mockup was wrong, not the board.
- Editing a row walks its settings with `[current]` in brackets; Enter accepts. Choice
  types list allowed values. Invalid input re-prompts and never raises.
- `[c]` prints the exact equivalent command line, copy-pasteable into a shell.
- The header shows model size against free VRAM (via `nvidia-smi`, absent silently if it
  is not available). Display only — see non-goals.

---

## 8. Launch sequence

1. Resolve values, build argv, `shlex.split` the extra-args row.
2. Identify the target port's owner: `netstat -ano` for the PID, `tasklist` for the name.
3. Dispatch on the owner:
   - **llama-server** → `[Y/n]` prompt → `taskkill /PID <pid> /F`.
   - **Any other process** → refuse, name the process, return to the board.
   - **Free** → proceed.
4. Spawn with `CREATE_NEW_CONSOLE`.
5. **Poll the port until it accepts a connection**, watching for the child dying
   (`Popen.poll()`). On success print URL and PID; on early exit report failure and point
   at the console window. Polling is condition-based with a progress tick, not a fixed
   sleep — a 20 GB model needs a generous ceiling.

Step 5 replaces the current unconditional `"Server started in new window."`, which is
printed even when the server dies during startup.

### Error handling

| Condition | Behaviour |
|---|---|
| Model file missing | Config listed as `!missing`; launch blocked |
| `llama_server` path missing | Hard startup error naming the configured path |
| Malformed config JSON | Report decode position; never overwrite the file |
| Invalid input on a row | Re-prompt; never raise |
| Interrupted save | Temp file + `os.replace` — original stays intact |
| Port held by a non-llama process | Refuse, name it, return to board |

---

## 9. Testing

Stdlib `unittest` in `Scripts/tests/`, run via `python -m unittest discover -s tests`.
No pip install.

**Anchor test:** load the migrated `gemma4dflash` config, build argv, and assert that
**every flag/value pair in the known-good hand-written command is present in the built
argv** — minus `--device Vulkan0`, unsupported by this build. Passing it exercises the
catalog, layering and spec-gating together.

Containment, not equality: the catalog always emits its valued settings, so argv also
carries `--temp`, `--top-k`, `-ctk`, `-ctv` and others the hand-written command omits by
relying on llama-server's own defaults. A paired negative assertion covers the other
direction — building a config with no `draft_model` must emit no `--spec-*` flag at all.

Around it:

- `test_config.py` — layering order; migration from a sample `model_profiles.json`; path
  relativising; save/load round-trip; the `canon()` dedup regression carried over from the
  current launcher.
- `test_catalog.py` — emission per type; bool omission when false; tri-state unset/on/off
  emitting nothing/`--flag`/`--no-flag`; `chat_template_kwargs` serialising to a compact
  JSON string and being omitted when empty; validator accept/reject per setting.
- **Spec-gating table (§5) gets one test per row**, since a single wrong rule here already
  slipped through review once:
  - `spec_type: none` emits no `--spec-*` flag at all.
  - `draft-dflash` without `draft_model` is rejected before launch, naming the omission.
  - `draft-mtp` emits `--spec-type draft-mtp` and the shared knobs, and **no**
    `--spec-draft-model`; setting one is rejected.
  - An `ngram-*` type emits `--spec-type` and shared knobs with no draft model required.
- **Second anchor test:** the `qwen3.8-preserve-thinking-coding` config builds argv
  containing `--kv-unified`, `--spec-type draft-mtp`, `--spec-draft-n-max 3`,
  `--spec-draft-p-min 0.75`, `--temp 0.6`, `--presence-penalty 0.0` and
  `--reasoning on`, and `--chat-template-kwargs {"preserve_thinking":true}`.
- `test_server.py` — port-owner parsing against a captured `netstat -ano` fixture string.
  No live sockets.
- `test_board.py` — input dispatch and row rendering through an injected input function.
  The terminal loop itself is not tested end-to-end.

---

## 10. Notes and follow-ups

- **`--device Vulkan0` is not supported by build 10453** — `--list-devices` reports only
  `CUDA0`. The known-good gemma4 command carries this flag; it is dropped in migration and
  in the anchor test. If a Vulkan-enabled build is installed later, device selection
  becomes a catalog row rather than an extra-args string.
- **`LLAMA.bat` was deleted** on 2026-08-17. It pointed at a nonexistent path
  (`D:\llama.cpp\models\Qwen3.6\...`) and is fully superseded by this design.
- **`enable_thinking` was moved off `chat_template_kwargs` onto `--reasoning on`** on
  2026-08-17. Build 10453 warns: "Setting 'enable_thinking' via --chat-template-kwargs is
  deprecated. Use --reasoning on / --reasoning off instead." Tested one kwarg at a time:
  `enable_thinking` warns, `preserve_thinking` does not. Neither is a parse error, so the
  original preset worked - but half of it was on a path the binary has announced it is
  retiring. The preset now sets `reasoning: "on"` and keeps only `preserve_thinking` in
  the template kwargs.
- **`--reasoning-preserve` and `chat_template_kwargs.preserve_thinking` are different
  mechanisms**, and both are catalogued. The template kwarg is passed through to the jinja
  template; the flag is a server-level setting that the help text notes only works with
  templates advertising `supports_preserve_reasoning`. The Qwen3.8 preset uses the kwarg,
  per the source config it was derived from. If thinking is not preserved in practice, the
  tri-state `reasoning_preserve` toggle is the second lever to try.
- **The `ngram-*` speculative families need 12 further flags** to be usable beyond their
  defaults. They are reachable through extra-args today. If one turns out to be worth
  using regularly, it becomes a conditional sub-group under row 10.
- **The `"it"` substring heuristic** in the current `infer_flags_from_name` matches the
  `it` inside `ornith`. The heuristic disappears with this refactor: new configs start
  from catalog and file defaults rather than guesses parsed out of filenames.
- Catalog values are pinned to build 10453. A llama.cpp rebuild that changes allowed
  values for `-ctk` / `--spec-type` needs a catalog update.
