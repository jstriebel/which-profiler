# Which Profiler, When? — demo walkthrough

Command walkthrough from the EuroPython 2026 talk.

## A: pure Python, stdlib profilers

Where every project starts: plain Python, stdlib tools only — one script, two
profiler kinds (instrumenting vs sampling), on CPython 3.15 with zero installs.

```bash
uv run a_pure_python.py --data s
uv run python -m cProfile -o a.pstats a_pure_python.py --data s
uv run python -c "import pstats; pstats.Stats('a.pstats').sort_stats('tottime').print_stats(5)"
```

Tachyon, same script, from the 3.15 stdlib:

```bash
uv run --no-project --python 3.15 python -m profiling.sampling run \
  -r 100 --flamegraph -o a_tachyon.html a_pure_python.py --data s
```

Both agree; cProfile adds significant overhead (it tracks call count), the
sampler is basically free.

## B: numpy, loading still dominates

Both profiler kinds agree the bottleneck is still loading — fix the file
format, not the compute.

```bash
uv run b_csv_load.py --data m
uv run python -m cProfile -o b.pstats b_csv_load.py --data m
uv run --with py-spy py-spy record -r 100 -o b.svg -- python b_csv_load.py --data m
```

cProfile now costs ~nothing: a handful of C calls instead of hundreds of
thousands of Python calls.

## C: HDF5 load, naive compute — the memory story

I/O fixed. A CPU+memory line profiler shows the naive colorcode allocating
full-size float64 temporaries.

```bash
uv run c_hdf5_load.py --data l
uv run --with scalene scalene run -o c.json c_hdf5_load.py --data l
uv run --with scalene scalene view --html c.json   # writes scalene-profile.html
```

## D: right-sized dtypes (memray)

memray quantifies the fix: peak memory and wall time both drop substantially,
at lower overhead than scalene.

```bash
uv run --with memray memray run -o c.bin c_hdf5_load.py --data l
uv run --with memray memray stats c.bin
uv run --with memray memray run -o d.bin d_dtypes.py --data l
uv run --with memray memray stats d.bin
uv run --with memray memray flamegraph -o d.html d.bin
```

Live alternative: `memray run --live d_dtypes.py --data l`.

## E: chunked processing

Tiling doesn't move less data; it just never holds it all at once. Peak memory
drops dramatically while total allocated bytes stay flat — chunking is a
*peak* technique.

```bash
uv run --with memray memray run -o e.bin e_chunked.py --data l
uv run --with memray memray stats e.bin
```

## F: numba JIT — the native blind spot

The jitted loop is invisible three different ways: default sampling can't see
it, `--native` shows confidently wrong symbols, and perf resolves the Python
frames but never the jitted kernel.

```bash
uv run f_jit.py --data l   # note: eager @njit compiles at import; naive timing misses it
uv run --with py-spy py-spy record -r 100 -o f.svg -- python f_jit.py --data l
uv run --with py-spy py-spy record -r 100 -o f_n.svg -n -- python f_jit.py --data l
PYTHONPERFSUPPORT=1 perf record -F 999 -g -- uv run python f_jit.py --data l
perf report -n -g --stdio | head -50
```

## G: attach to a live server

Production case: no restart, no code change.

```bash
uv run g_server.py --duration 120 --data data/m &
uvx py-spy record -r 100 -o g.svg --pid $(pgrep -n -f g_server.py) --duration 20
```

The server serves right through it, undisturbed.

## Closing: which-profiler

One tool to generate outputs like above, depending on your needs:

```bash
uvx which-profiler                # interactive: one question
uvx which-profiler --all          # the full landscape
uvx which-profiler --nosy         # ask more questions
uvx which-profiler --tool memray --view flamegraph -- d_dtypes.py --data l
```
