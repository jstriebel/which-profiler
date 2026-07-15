# which-profiler

Which Python profiler fits your workload? Filter by focus, attach mode, and
more; get a runnable command.

## What it does

A **filtered catalog**: describe your workload (what you care about, attach
vs launch, target Python) and `which-profiler` narrows the options and
**ranks the profilers by measured overhead**. Each entry prints a
copy-paste-runnable `uv`-based command & useful information.

## Install

```bash
uvx which-profiler            # run without installing
uv tool install which-profiler
```

Only runtime dependency is `typer`. Runs on Python 3.10+.

## Usage

```bash
which-profiler                          # interactive: one question, ranked catalog
which-profiler --nosy                   # interactive: also asks attach/python/native/view/rate
which-profiler --all                    # full landscape (incompatible tools tagged, not hidden)
which-profiler --focus time --python 3.15
which-profiler pytest                   # bare console-command target
which-profiler python -m my_module      # same, python-invocation form
which-profiler --focus memory -- script.py --arg   # script target after --
which-profiler --pid 12345              # attach-capable tools only
which-profiler --tool py-spy pytest     # exactly this tool (py-spy or py_spy both work)
which-profiler --focus time --view flamegraph --run pytest   # build + run top pick
which-profiler --focus time --json      # machine-readable, no prompts
```

## The talk

Come see **"uvx which-profiler: Which Profiler, When?"** at EuroPython 2026:

EuroPython 2026, Kraków

📍 **Room S2**

📅 **Wednesday, 15 July 2026**

🕐 **15:25**

👉 https://ep2026.europython.eu/session/uvx-which-profiler-which-profiler-when/

### Presenter mode

`scripts/demo-teleprompter.sh` is a live-demo teleprompter for the talk. It
reads the ```` ```bash ```` blocks straight out of `talk/WALKTHROUGH.md` (the
single source of truth, no duplicated command list) and walks you through
them one at a time. Press a key to advance, the command lands on an editable,
pre-filled prompt so you can fill in placeholders like `<PID>`/`<size>`/`<tool>`
live, then Enter runs it.

```bash
scripts/demo-teleprompter.sh              # interactive presenter mode
scripts/demo-teleprompter.sh --list       # print every parsed step, run nothing
scripts/demo-teleprompter.sh --start 7    # jump straight to step 7
```

Per-step keys: `Enter`/`n` next · `s` skip · `p` previous · `r` re-run · `q`
quit. Defaults to running from `examples/image_analysis/`; see `--help`.

## Potential profilers to include in the future

- [line_profiler](https://github.com/pyutils/line_profiler)
- [Austin](https://github.com/P403n1x87/austin)
- [Yappi](https://github.com/sumerc/yappi)
- [Fil](https://github.com/pythonspeed/filprofiler)
- [Guppy3](https://github.com/zhuyifei1999/guppy3)

## Development

Setup via [mise](https://mise.jdx.dev):
```bash
mise run install
```

```bash
mise run fix
mise run check
mise run test       # uv run pytest in dev venv (.venv, pinned to .python-version)
mise run test-all   # full matrix: root tests on 3.10-3.15 + examples tests on 3.14
```

`test-all` runs `scripts/test-matrix.sh`, which tests each supported Python in
its own isolated venv under `.venvs/py<version>/` (gitignored) so the shared
dev `.venv` is never resynced to a different interpreter. It prints a
`python -> pass/fail/skip` summary table at the end; 3.15 (still prerelease)
degrades a dependency-install failure to a recorded skip instead of a hard
failure.

## Where the numbers come from

Overhead ranking is based on a benchmark from 2026-07-13:
ThinkPad X1 Carbon Gen5, all samplers forced to 100 Hz for
parity, median-of-7 repeats, over a tight numeric loop and a call-dense
workload. The CLI (and `--json`) only show the coarse category
(negligible/low/moderate/high); reproducible scripts and further measurements
will come later.
