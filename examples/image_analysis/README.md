# Image-analysis example arc

A probability-map colorcoding pipeline (per-pixel class probabilities from a
small RandomForest segmenter, colorized into an RGB image), evolved step by
step.

This directory is its own `uv` project (`pyproject.toml`, own lock/venv),
kept separate from the top-level `which-profiler` package so that package
stays free of numpy/h5py/scikit-image/scikit-learn/numba. Requires Python
3.14+. On CPython 3.15, numpy/h5py/scikit-image/scikit-learn/numba have no
wheels yet (3.15 is still beta), so steps B–G below need 3.14. The exception
is `a_pure_python.py`.

`a_pure_python.py` has zero third-party imports (it parses the CSVs by hand
and colorcodes with plain nested loops), so it runs fine standalone on any
CPython, 3.15 included, without this project's venv at all (`--no-project`
skips trying to sync numpy et al.). See `tests/test_a_pure_python.py` in
the top-level repo.

| script | change vs previous | profiler that motivates it |
|---|---|---|
| `a_pure_python.py` | stdlib only, nested-loop everything (no numpy) | cProfile / py-spy: hotspot is Python bytecode, not a C call, and it's the one script here that runs on 3.15 today |
| `b_csv_load.py` | switch to numpy (CSV load still dominates) | cProfile / py-spy: the hotspot is `np.loadtxt` |
| `c_hdf5_load.py` | HDF5 load (compute still naive) | scalene: float64 temporaries, max recomputed |
| `d_dtypes.py` | right-sized dtypes, argmax reuse | memray: allocation volume shrinks vs C |
| `e_chunked.py` | process in tiles | tachyon (3.15): peak memory collapses |
| `f_jit.py` | numba-jitted loop | py-spy --native / perf: the native blind spot |
| `g_server.py` | serve step D in a loop | py-spy / tachyon attach: profile a live PID |

All commands below assume you're in this directory (`cd
examples/image_analysis`); prefix with `uv run --project
examples/image_analysis ...` to run them from the repo root instead.

## Generate the data

```bash
uv run generate_data.py            # sizes s m l
uv run generate_data.py --sizes s  # just s
uv run generate_data.py --crop-size 300  # quick/small
```

Sizes tile the same 900×900 base: `s` (1×), `m` (2×), `l` (4×). Disk usage is
dominated by the CSV form (steps A–B): roughly ~70MB for `s`, ~280MB for `m`,
~1.1GB for `l`. Data lands in `examples/image_analysis/data/` (gitignored).

## Run a step

```bash
uv run a_pure_python.py                                      # stdlib only
uv run --no-project --python 3.15 a_pure_python.py --data s  # same, on 3.15
uv run c_hdf5_load.py             # default --data s
uv run d_dtypes.py --data m       # or l; also accepts a path
uv run g_server.py --duration 10  # prints READY pid=<PID>
```

Every script prints `processed in N.NNs` to stderr.

## Which profiler?

Ask the CLI in this repo; it prints the exact command for each step. From
this directory (the CLI lives in the repo-root project):

```bash
uv run --project ../.. which-profiler -- c_hdf5_load.py --data l
uv run --project ../.. which-profiler --focus memory -- c_hdf5_load.py --data l
uv run --project ../.. which-profiler --tool memray --view flamegraph -- d_dtypes.py --data l
uv run --project ../.. which-profiler --pid <PID>    # while g_server.py is running
```

The emitted commands (`uv run --with <tool> ...`) are meant to be run from
this directory too, so the profiled script sees this project's venv. One
exception to copy-paste: for the 3.15/stdlib pair on `a_pure_python.py`
(cProfile, Tachyon), prefix the emitted command with
`uv run --no-project --python 3.15 ...`, never plain `--python 3.15` here,
or uv resyncs this project's 3.14 venv (undo with `uv sync`).
