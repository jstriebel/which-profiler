"""Curated profiler catalog: data, command templates, filtering, ranking.

Typer-free so the same core can back an Agent Skill; ``cli.py`` is the only
module that imports typer.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

_PLACEHOLDER = "<your-script.py>"

FOCUS_CHOICES = ("any", "time", "memory", "both")
# Kinds describe *what a human sees*, not the file type. "stats" covers
# flat/sorted aggregate tables (cProfile's pstats browser, memray's summary,
# perf report); file-type words like html/svg/text live in the format
# registry below, never as a view kind.
VIEW_CHOICES = ("flamegraph", "call-tree", "timeline", "line", "stats")

PLATFORM_NAMES = {"linux": "linux", "darwin": "macOS", "win32": "windows"}
_ALL_PLATFORMS = {"linux", "darwin", "win32"}

_LOWEST_OVERHEAD_KEYS = {"py_spy", "tachyon"}


# --- output format registry --------------------------------------------------
#
# ``Tool.views`` maps a view *kind* (from VIEW_CHOICES) to a concrete format
# *name* (e.g. "svg", "pstats", "speedscope"). The same format name can be
# reused by several tools, so its meaning lives here once: whether it's
# something a person can open and read as-is ("viz"), or a data/interchange
# format meant for another tool to render ("data"), plus a one-line plain
# description of what to actually do with a file in that format.


@dataclass(frozen=True)
class Format:
    kind: str  # "viz" | "data"
    blurb: str  # one-line, plain-English "what do I do with this file"


FORMATS: dict[str, Format] = {
    # visualizations: open/read the file directly, no extra tool needed
    "html": Format("viz", "self-contained HTML report, open directly in a browser"),
    "svg": Format("viz", "SVG image, open directly in a browser"),
    "heatmap": Format(
        "viz",
        "static HTML site (source-line heatmap); it's a directory, open its index.html in a browser",
    ),
    "text": Format(
        "viz", "human-readable text, read directly in the terminal or a file"
    ),
    "cli": Format("viz", "rendered directly in the terminal"),
    "report": Format(
        "viz", "rendered as an interactive TUI in the terminal (`perf report`)"
    ),
    "stats": Format("viz", "human-readable summary printed to the terminal"),
    "tree": Format("viz", "human-readable allocation tree printed to the terminal"),
    # data / interchange formats: meant for another viewer, not for reading by hand
    "pstats": Format(
        "data",
        "binary cProfile-compatible stats, read with `python -m pstats` or a GUI viewer like snakeviz",
    ),
    "speedscope": Format(
        "data",
        "JSON for speedscope.app; open https://www.speedscope.app and drop the file in",
    ),
    "raw": Format(
        "data",
        "folded/collapsed stack lines (one per unique stack + sample count); "
        "feed to Brendan Gregg's FlameGraph.pl or inferno to render an SVG",
    ),
    "collapsed": Format(
        "data",
        "folded/collapsed stack lines; feed to FlameGraph.pl/inferno to render an SVG",
    ),
    "json": Format(
        "data",
        "structured JSON, meant for the tool's own report/view step, not for reading by hand",
    ),
    "chrome-trace": Format(
        "data",
        "Chrome Trace Format JSON; load into chrome://tracing or the Perfetto UI",
    ),
    "gecko": Format(
        "data",
        "Firefox Profiler's timeline JSON; open https://profiler.firefox.com and drop the file in",
    ),
}


# --- target parsing ---------------------------------------------------------


def is_python_token(tok: str) -> bool:
    return tok == "python" or tok.startswith("python3")


def parse_target(target: str | None) -> tuple[str, str, str]:
    """Return ``(mode, name, args)`` with mode ``"module"`` or ``"script"``.

    Accepted target shapes: ``typer`` (bare script/console-command), ``python
    -m typer``, ``script.py --arg``, ``-m typer``. A leading
    ``python``/``python3``/``python3.X`` token is stripped. Empty target
    yields a placeholder script. ``module`` mode is only ever produced by an
    explicit     ``-m``/``--module``. We never guess that a bare word is an
    importable module, since it could just as easily be a standalone script
    installed on ``$PATH`` with no importable module behind it at all.
    """
    if not target or not target.strip():
        return ("script", _PLACEHOLDER, "")
    toks = shlex.split(target)
    if toks and is_python_token(toks[0]):
        toks = toks[1:]
    if not toks:
        return ("script", _PLACEHOLDER, "")
    first = toks[0]
    if first in ("-m", "--module"):
        name = toks[1] if len(toks) > 1 else "<module>"
        return ("module", name, " ".join(toks[2:]))
    return ("script", first, " ".join(toks[1:]))


def _tail(mode: str, name: str, args: str) -> str:
    """``-m pkg args`` or ``script.py args``, the part after the interpreter."""
    if mode == "module":
        head = f"-m {name}"
    else:
        head = name
        if name != _PLACEHOLDER and "/" not in name and not name.endswith(".py"):
            # A bare word with no path separator/extension (e.g. `typer`) is
            # a console-script installed on $PATH, not a file relative to
            # the cwd, and not necessarily an importable module either (it
            # might just be a standalone script someone dropped on $PATH).
            # Either way it IS a real file, so resolve it with `$(which ...)`
            # at shell run-time instead of passing the bare name verbatim
            # (which fails with FileNotFoundError/ModuleNotFoundError since
            # no such file/module exists relative to the cwd). The
            # placeholder (no target given at all) is passed through as-is
            # for the user to fill in; it isn't a real name to resolve.
            head = f"$(which {name})"
    return f"{head} {args}".rstrip()


def _seconds(rate: int) -> str:
    """Hz -> interval seconds for interval-flag samplers (pyinstrument, scalene)."""
    return f"{1.0 / rate:g}"


# --- tool model ---------------------------------------------------------------


@dataclass
class Tool:
    """One profiler entry; ranking uses the exact ``call_heavy`` ratio."""

    key: str
    display_name: str
    mechanism: str  # e.g. "sampling, out-of-process"
    marker: str  # ⏱ and/or 💾
    stdlib: bool
    min_python: tuple[int, int]
    focus: set[str]  # subset of {"time", "memory"}
    platforms: set[str]  # subset of {"linux", "darwin", "win32"}
    attach: bool
    native: bool
    views: dict[
        str, list[str]
    ]  # view-kind -> formats available for it (first = default)
    overhead: dict[str, float] | None  # keys cpu_bound / call_heavy
    notes: list[str]
    requires: str | None  # None | "ptrace" | "perf_events"
    install_hint: str
    url: str
    # What actually drives the worst-case ("call_heavy" key) ratio. True for
    # every call/frame tracer or sampler in this catalog, but memray is an
    # allocation tracer: its cost tracks malloc frequency, not call count,
    # even though it happens to be measured on the same synthetic benchmark.
    overhead_driver: str = "call-heavy code"

    def build_command(
        self,
        target: str | None = None,
        pid: int | None = None,
        native: bool = False,
        rate: int | None = None,
        view: str | None = None,
        output: str | None = None,
    ) -> str | None:
        """Copy-paste-runnable uv-based command, or ``None`` when the tool
        cannot handle this target at all."""
        mode, name, args = parse_target(target)
        tail = _tail(mode, name, args)
        key = self.key

        if key == "cprofile":
            out = output or "out.pstats"
            return f"uv run python -m cProfile -o {out} {tail}".rstrip()

        if key == "pyinstrument":
            as_speedscope = view == "flamegraph"
            out = output or ("out.speedscope.json" if as_speedscope else "out.html")
            parts = ["uv", "run", "--with", "pyinstrument", "pyinstrument"]
            if as_speedscope:
                parts += ["-r", "speedscope"]
            if rate:
                parts += ["-i", _seconds(rate)]
            parts += ["-o", out, tail]
            return " ".join(parts).rstrip()

        if key == "py_spy":
            r = rate or 100
            out = output or "out.svg"
            if pid is not None:
                # Out-of-process attach needs no project env; uvx suffices.
                parts = ["uvx", "py-spy", "record", "-r", str(r), "-o", out]
            else:
                parts = [
                    "uv",
                    "run",
                    "--with",
                    "py-spy",
                    "py-spy",
                    "record",
                    "-r",
                    str(r),
                    "-o",
                    out,
                ]
            if native:
                parts.append("-n")
            if pid is not None:
                parts += ["--pid", str(pid), "--duration", "30"]
            else:
                parts += ["--", f"python {tail}".rstrip()]
            return " ".join(parts)

        if key == "tachyon":
            r = rate or 100
            sub = "attach" if pid is not None else "run"
            parts = [
                "uv",
                "run",
                "--python",
                "3.15",
                "python",
                "-m",
                "profiling.sampling",
                sub,
                "-r",
                str(r),
            ]
            if view == "call-tree":
                # pstats format is version-sensitive; read back with the same
                # interpreter (3.15) that wrote it, not the project's default.
                parts.append("--pstats")
                out = output or "out.pstats"
            elif view == "timeline":
                parts.append("--gecko")
                out = output or "out.gecko.json"
            elif view == "line":
                # --heatmap writes a directory (index.html + per-file pages),
                # not a single file; the "name" is a directory basename.
                parts.append("--heatmap")
                out = output or "out_heatmap"
            else:
                # Bare -o writes a binary dump; --flamegraph makes it real html.
                parts.append("--flamegraph")
                out = output or "out.html"
            if native:
                parts.append("--native")
            if pid is not None:
                parts += ["-d", "30", "-o", out, str(pid)]
            else:
                parts += ["-o", out, tail]
            return " ".join(parts).rstrip()

        if key == "scalene":
            out = output or "out.json"
            parts = ["uv", "run", "--with", "scalene", "scalene", "run"]
            if rate:
                parts += ["--cpu-sampling-rate", _seconds(rate)]
            if mode == "module":
                # scalene `run` only accepts a script path, no `-m`. Write a
                # tiny shim that does what `-m` would (runpy.run_module) and
                # profile that instead. Verified to work end-to-end.
                shim = f"_scalene_shim_{name.replace('.', '_').replace('-', '_')}.py"
                write_shim = (
                    f'printf \'import runpy\\nrunpy.run_module("{name}", '
                    f'run_name="__main__")\\n\' > {shim}'
                )
                parts += ["-o", out, shim]
                if args:
                    parts += ["---", args]
                return f"{write_shim} && {' '.join(parts)}".rstrip()
            # For script mode, `tail` already resolved a bare console-script
            # word (e.g. `typer`) to `$(which typer)` via `_tail` above.
            parts += ["-o", out, tail]
            return " ".join(parts).rstrip()

        if key == "memray":
            out = output or "out.bin"
            if pid is not None:
                # attach: memray must already be importable in the TARGET's env
                # (the injected build has to match); this is the best-effort
                # command; see the tool's attach note for the caveats.
                return f"uv run --with memray memray attach -o {out} {pid}"
            parts = ["uv", "run", "--with", "memray", "memray", "run"]
            if native:
                parts.append("--native")
            parts += ["-o", out, tail]
            return " ".join(parts).rstrip()

        if key == "viztracer":
            out = output or "out.html"
            if pid is not None:
                # attach: needs viztracer importable in the TARGET's env and
                # gdb (Linux) / lldb (macOS) to inject; no Windows support.
                return f"uv run --with viztracer viztracer --attach {pid} -o {out}".rstrip()
            return f"uv run --with viztracer viztracer -o {out} {tail}".rstrip()

        if key == "perf":
            r = rate or 999
            return (
                f"PYTHONPERFSUPPORT=1 perf record -F {r} -g -- uv run python {tail}"
            ).rstrip()

        raise ValueError(f"unknown tool key: {key}")  # pragma: no cover

    def follow_up(
        self, view: str | None = None, output: str | None = None
    ) -> str | None:
        """Display-only report step shown after the capture command, if any."""
        if self.key == "cprofile":
            return f"uv run python -m pstats {output or 'out.pstats'}"
        if self.key == "scalene":
            # scalene 2.3+ dropped `run --html`; rendering is now a separate
            # `view` step that reads the JSON `run` wrote. HTML is the
            # default render; `scalene view --cli` gives the same line
            # annotations as a terminal alternative (see notes).
            return f"uv run --with scalene scalene view --html {output or 'out.json'}"
        if self.key == "tachyon":
            if view == "call-tree":
                # Same interpreter that wrote the pstats file (3.15) reads it back.
                return f"uv run --python 3.15 python -m pstats {output or 'out.pstats'}"
            return None
        if self.key == "memray":
            out = output or "out.bin"
            reporter = {"stats": "stats", "call-tree": "tree"}.get(
                view or "", "flamegraph"
            )
            return f"uv run --with memray memray {reporter} {out}"
        if self.key == "perf":
            if view == "flamegraph":
                return "perf script | stackcollapse-perf.pl | flamegraph.pl > out.svg"
            return "perf report -n -g --no-children"
        return None

    def overhead_category(self) -> str | None:
        """Coarse worst-case bucket: negligible / low / moderate / high.

        Numeric ratios are noisy to measure precisely and vary by workload,
        so both the human output and --json stick to the category; exact
        ratios live in the profiler-landscape dataset.
        """
        if self.overhead is None:
            return None
        worst = self.overhead["call_heavy"]
        if worst < 1.15:
            return "negligible"
        if worst < 1.5:
            return "low"
        if worst < 2.0:
            return "moderate"
        return "high"

    def overhead_label(self) -> str:
        """Coarse category label shown in the CLI; see ``overhead_category``."""
        category = self.overhead_category()
        if category is None:
            return "overhead not measured"
        if category == "high":
            return f"overhead: high (on {self.overhead_driver})"
        return f"overhead: {category}"

    def views_label(self) -> tuple[str, str]:
        """(\"view directly\" line, \"data formats\" line) for the CLI.

        Every format under a kind is shown once, sorted into whichever line
        matches its ``FORMATS[...].kind``: human-viewable vs. an
        interchange format for another tool.
        """
        viz_parts: list[str] = []
        data_parts: list[str] = []
        for kind, formats in self.views.items():
            for fmt in formats:
                entry = f"{kind} ({fmt})"
                if FORMATS[fmt].kind == "data":
                    data_parts.append(entry)
                else:
                    viz_parts.append(entry)
        return ", ".join(viz_parts), ", ".join(data_parts)

    def views_detailed(self) -> list[dict[str, str]]:
        """Structured view info for --json: kind/format/data-or-viz/blurb."""
        return [
            {
                "view": kind,
                "format": fmt,
                "kind": FORMATS[fmt].kind,
                "description": FORMATS[fmt].blurb,
            }
            for kind, formats in self.views.items()
            for fmt in formats
        ]

    def python_min_str(self) -> str:
        return f"{self.min_python[0]}.{self.min_python[1]}"

    def platforms_label(self) -> str:
        order = ["linux", "darwin", "win32"]
        return "/".join(PLATFORM_NAMES[p] for p in order if p in self.platforms)


CATALOG: list[Tool] = [
    Tool(
        key="cprofile",
        display_name="cProfile",
        mechanism="tracing",
        marker="⏱",
        stdlib=True,
        min_python=(3, 8),
        focus={"time"},
        platforms=set(_ALL_PLATFORMS),
        attach=False,
        native=False,
        views={"stats": ["pstats"]},
        overhead={"cpu_bound": 1.02, "call_heavy": 2.91},
        notes=[],
        requires=None,
        install_hint="stdlib",
        url="https://docs.python.org/3/library/profile.html",
    ),
    Tool(
        key="pyinstrument",
        display_name="pyinstrument",
        mechanism="sampling, in-process",
        marker="⏱",
        stdlib=False,
        min_python=(3, 8),
        focus={"time"},
        platforms=set(_ALL_PLATFORMS),
        attach=False,
        native=False,
        views={"call-tree": ["html", "text"], "flamegraph": ["speedscope"]},
        overhead={"cpu_bound": 1.00, "call_heavy": 2.48},
        notes=[
            "Samples only at call boundaries, tight loops with no function calls won't show up.",
            "Default output is HTML, add `-r text` for a plain-terminal call tree instead.",
        ],
        requires=None,
        install_hint="",
        url="https://pyinstrument.readthedocs.io",
    ),
    Tool(
        key="py_spy",
        display_name="py-spy",
        mechanism="sampling, out-of-process",
        marker="⏱",
        stdlib=False,
        min_python=(3, 8),
        focus={"time"},
        platforms=set(_ALL_PLATFORMS),
        attach=True,
        native=True,
        views={"flamegraph": ["svg", "raw"]},
        overhead={"cpu_bound": 1.05, "call_heavy": 1.10},
        notes=[
            "Excludes idle time, add --idle to include wall-clock waits.",
            "Default output is SVG, add `-f raw` for folded stack lines instead.",
        ],
        requires="ptrace",
        install_hint="",
        url="https://github.com/benfred/py-spy",
    ),
    Tool(
        key="tachyon",
        display_name="Tachyon (profiling.sampling)",
        mechanism="sampling, out-of-process",
        marker="⏱",
        stdlib=True,
        min_python=(3, 15),
        focus={"time"},
        platforms=set(_ALL_PLATFORMS),
        attach=True,
        native=True,
        views={
            "flamegraph": ["html", "collapsed"],
            "call-tree": ["pstats"],
            "timeline": ["gecko"],
            "line": ["heatmap"],
        },
        overhead={"cpu_bound": 0.99, "call_heavy": 1.01},
        notes=[
            "--mode wall profiles wall-clock time (waits included) instead of CPU.",
            "--view line (--heatmap) writes a directory, not a file, open <name>/index.html.",
            "Default output is HTML, add --collapsed for folded stack lines instead.",
            "Also supports --jsonl (streaming JSON) and --diff-flamegraph BASELINE (compare runs).",
        ],
        requires="ptrace",
        install_hint="stdlib (Python 3.15+)",
        url="https://docs.python.org/3.15/library/profiling.html",
    ),
    Tool(
        key="scalene",
        display_name="scalene",
        mechanism="sampling, in-process",
        marker="⏱💾",
        stdlib=False,
        min_python=(3, 8),
        focus={"time", "memory"},
        platforms=set(_ALL_PLATFORMS),
        attach=False,
        native=True,
        views={"line": ["html", "cli", "json"]},
        overhead={"cpu_bound": 1.51, "call_heavy": 1.63},
        notes=[
            "No --native flag needed, splits Python vs native time per line automatically "
            "(a time split, not native stack frames).",
            "Line attribution can spill native time onto the next line.",
            "Inflates the target's memory usage, treat absolute numbers with care.",
            "Module targets (`-m pkg`) run via a generated shim script, no native -m support.",
            "Default output is HTML, use `scalene view --cli` for the same in the terminal instead.",
        ],
        requires=None,
        install_hint="",
        url="https://github.com/plasma-umass/scalene",
    ),
    Tool(
        key="memray",
        display_name="memray",
        mechanism="allocation tracing",
        marker="💾",
        stdlib=False,
        min_python=(3, 8),
        focus={"memory"},
        platforms={"linux", "darwin"},
        attach=True,
        native=True,
        views={"flamegraph": ["html"], "call-tree": ["tree"], "stats": ["stats"]},
        overhead={"cpu_bound": 1.03, "call_heavy": 2.34},
        overhead_driver="allocation-heavy code",
        notes=[
            "Inflates the target's memory usage, treat absolute numbers with care.",
            "`run --live` gives an interactive live TUI directly, skip the reporter step.",
            "Attach needs gdb/lldb and a matching memray build in the target's own environment.",
        ],
        requires="ptrace",
        install_hint="Linux/macOS only",
        url="https://bloomberg.github.io/memray/",
    ),
    Tool(
        key="viztracer",
        display_name="viztracer",
        mechanism="tracing",
        marker="⏱",
        stdlib=False,
        min_python=(3, 8),
        focus={"time"},
        platforms=set(_ALL_PLATFORMS),
        attach=True,
        native=False,
        views={"timeline": ["html", "chrome-trace"]},
        overhead={"cpu_bound": 1.00, "call_heavy": 2.48},
        notes=[
            "Default ring buffer silently truncates early data, size it with --tracer_entries.",
            "Default output is HTML, add `-o out.json` for raw Chrome Trace Format JSON instead.",
            "--attach <pid> needs viztracer importable in the target's env and gdb/lldb to "
            "inject, no Windows support.",
        ],
        requires=None,
        install_hint="",
        url="https://viztracer.readthedocs.io",
    ),
    Tool(
        key="perf",
        display_name="perf",
        mechanism="sampling, out-of-process",
        marker="⏱",
        stdlib=False,
        min_python=(3, 12),  # PYTHONPERFSUPPORT trampoline
        focus={"time"},
        platforms={"linux"},
        attach=False,
        native=True,
        views={"flamegraph": ["svg"], "call-tree": ["report"]},
        overhead={"cpu_bound": 1.02, "call_heavy": 1.21},
        notes=[
            "Needs PYTHONPERFSUPPORT=1 set before the target starts.",
            "Launch-only for Python frames, the trampoline must be enabled when the process "
            "starts, so attaching to an already-running process only sees C/kernel frames.",
        ],
        requires="perf_events",
        install_hint="Linux-only, system package (not pip/uv-installable, e.g. `sudo apt install linux-perf`)",
        url="https://docs.python.org/3/howto/perf_profiling.html",
    ),
]

BY_KEY: dict[str, Tool] = {t.key: t for t in CATALOG}


# --- filtering & ranking -------------------------------------------------------


def rank(tools: list[Tool], focus: str | None = None) -> list[Tool]:
    """Ascending by exact ``call_heavy`` overhead; unswept tools sort last.

    For a pure ``"memory"`` focus, dedicated allocation-tracing tools (memray)
    are ranked ahead of mixed sampling profilers (scalene) regardless of raw
    overhead: a sampler estimates memory indirectly and can miss/misattribute
    allocations, while an instrumenting tracer sees every allocation. Raw
    overhead is only used to break ties within each group.
    """
    dedicated_memory = focus == "memory"
    return sorted(
        tools,
        key=lambda t: (
            dedicated_memory and t.focus != {"memory"},
            t.overhead is None,
            t.overhead["call_heavy"] if t.overhead else 0.0,
        ),
    )


def python_compatible(tool: Tool, target_py: tuple[int, int] | None) -> bool:
    return target_py is None or tool.min_python <= target_py


def focus_matches(tool: Tool, focus: str | None) -> bool:
    if focus in (None, "any"):
        return True
    if focus == "both":
        return {"time", "memory"} <= tool.focus
    return focus in tool.focus


def filter_tools(
    *,
    focus: str | None = None,  # any | time | memory | both
    mode: str | None = None,  # "attach" | "launch" | None
    lowest_overhead: bool = False,
    stdlib_only: bool = False,
    native: bool = False,
    view: str | None = None,
    target_py: tuple[int, int] | None = None,  # None = no version filter
    platform: str | None = None,  # None = no platform filter
    show_all: bool = False,
) -> list[Tool]:
    """Apply the filters (each prunes independently), then rank.

    ``show_all`` skips python-version and platform hiding; the caller tags
    incompatible tools instead.
    """
    tools = list(CATALOG)
    if mode == "attach":
        tools = [t for t in tools if t.attach]
    tools = [t for t in tools if focus_matches(t, focus)]
    if lowest_overhead:
        tools = [t for t in tools if t.key in _LOWEST_OVERHEAD_KEYS]
    if stdlib_only:
        tools = [t for t in tools if t.stdlib]
    if native:
        tools = [t for t in tools if t.native]
    if view:
        tools = [t for t in tools if view in t.views]
    if not show_all:
        tools = [t for t in tools if python_compatible(t, target_py)]
        if platform is not None:
            tools = [t for t in tools if platform in t.platforms]
    return rank(tools, focus=focus)
