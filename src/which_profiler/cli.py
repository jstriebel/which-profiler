"""``which-profiler`` — filtered profiler catalog.

Filters narrow the roster; survivors are ranked by measured overhead so a
non-empty filter always has a clear top pick. Three ways in: interactive (one
question), non-interactive flags, and ``--json`` (no prompts).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import typer

from . import catalog, preflight
from .catalog import Tool

app = typer.Typer(
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)

_FOCUS_LABELS = {
    "any": "any / not sure",
    "time": "time",
    "memory": "memory",
    "both": "both (time + memory)",
}


def _parse_python(value: str) -> tuple[int, int] | None:
    """``"3.15"`` -> ``(3, 15)``; ``"any"`` (case-insensitive) -> ``None``."""
    if value.strip().lower() == "any":
        return None
    parts = value.strip().split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError) as err:
        raise typer.BadParameter(
            f"--python must look like X.Y or 'any', got {value!r}"
        ) from err


def _detected_python() -> tuple[int, int]:
    return (sys.version_info.major, sys.version_info.minor)


def _target_looks_duplicated(target: str | None) -> bool:
    """Detect the classic ``typer --tool scalene -- python -m typer`` mistake.

    click/typer glue any unrecognized bare positional (a stray ``typer``
    before the options) onto whatever follows a literal ``--``, so the
    resulting target string is ``"typer python -m typer"``. ``parse_target``
    then reads that as a *script* named ``typer`` whose "args" are themselves
    a full interpreter invocation, a strong smell nobody would type on
    purpose, and the tell-tale sign of this ambiguous mix.
    """
    if not target:
        return False
    mode, _name, args = catalog.parse_target(target)
    if mode != "script" or not args:
        return False
    first = args.split()[0]
    return catalog.is_python_token(first)


def _tags(
    tool: Tool, target_py: tuple[int, int] | None, trampoline_ok: bool
) -> list[str]:
    """Incompatibility tags shown in --all / --tool modes."""
    tags: list[str] = []
    if not catalog.python_compatible(tool, target_py):
        tags.append(f"[needs {tool.python_min_str()}+]")
    if sys.platform not in tool.platforms:
        tags.append(f"[{tool.platforms_label()} only]")
    if tool.key == "perf" and not trampoline_ok:
        tags.append("[no perf trampoline in this build]")
    return tags


def _rec_dict(
    tool: Tool,
    rank: int,
    command: str | None,
    view: str | None,
    output: str | None,
) -> dict[str, Any]:
    return {
        "key": tool.key,
        "display_name": tool.display_name,
        "rank": rank,
        "marker": tool.marker,
        "mechanism": tool.mechanism,
        "command": command,
        "follow_up": tool.follow_up(view, output),
        "python_min": tool.python_min_str(),
        "platforms": sorted(tool.platforms),
        "views": tool.views_detailed(),
        "notes": tool.notes,
        "overhead_category": tool.overhead_category(),
        "overhead_driver": tool.overhead_driver,
        "focus": sorted(tool.focus),
        "stdlib": tool.stdlib,
        "attach": tool.attach,
        "native": tool.native,
        "requires": tool.requires,
        "install_hint": tool.install_hint,
        "url": tool.url,
    }


def _ask_focus() -> str:
    typer.echo("")
    typer.secho("What do you care about?", bold=True)
    for i, name in enumerate(catalog.FOCUS_CHOICES, start=1):
        typer.echo(f"  {i}. {_FOCUS_LABELS[name]}")
    while True:
        choice = typer.prompt("choice", type=int, default=1)
        if 1 <= choice <= len(catalog.FOCUS_CHOICES):
            return catalog.FOCUS_CHOICES[choice - 1]
        typer.secho(f"pick 1-{len(catalog.FOCUS_CHOICES)}", fg=typer.colors.RED)


def _ask_attach() -> int | None:
    """Nosy prompt for what ``--pid`` normally covers."""
    typer.echo("")
    if typer.confirm(
        "Attach to a running process instead of launching one?", default=False
    ):
        return int(typer.prompt("PID", type=int, default=1234))
    return None


def _ask_python() -> str:
    """Nosy prompt for what ``--python`` normally covers."""
    typer.echo("")
    default = "{}.{}".format(*_detected_python())
    return str(typer.prompt("Target python version (X.Y, or 'any')", default=default))


def _ask_native() -> bool:
    """Nosy prompt for what ``--native`` normally covers."""
    typer.echo("")
    return typer.confirm(
        "Keep only tools with native-frame support?",
        default=False,
    )


def _ask_view() -> str | None:
    """Nosy prompt for what ``--view`` normally covers."""
    typer.echo("")
    typer.secho("Preferred view?", bold=True)
    typer.echo("  0. any / not sure")
    for i, name in enumerate(catalog.VIEW_CHOICES, start=1):
        typer.echo(f"  {i}. {name}")
    choice = typer.prompt("choice", type=int, default=0)
    if 1 <= choice <= len(catalog.VIEW_CHOICES):
        return catalog.VIEW_CHOICES[choice - 1]
    return None


def _ask_rate() -> int | None:
    """Nosy prompt for what ``--rate`` normally covers."""
    typer.echo("")
    value = typer.prompt(
        "Sampling rate in Hz (blank for each tool's default)",
        default="",
        show_default=False,
    )
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        typer.secho(
            "not a number; using each tool's default rate.", fg=typer.colors.YELLOW
        )
        return None


def _render(
    tools: list[Tool],
    *,
    target: str | None,
    pid: int | None,
    native: bool,
    rate: int | None,
    view: str | None,
    output: str | None,
    attach: bool,
    target_py: tuple[int, int] | None,
    trampoline_ok: bool,
    tagged: bool,
) -> list[tuple[Tool, str | None]]:
    """Print the ranked catalog; return ``(tool, command)`` pairs in order."""
    built: list[tuple[Tool, str | None]] = []
    data_formats: dict[str, str] = {}  # data-format name -> blurb, in print order
    for rank, tool in enumerate(tools, start=1):
        command = tool.build_command(
            target=target, pid=pid, native=native, rate=rate, view=view, output=output
        )
        built.append((tool, command))

        tags = _tags(tool, target_py, trampoline_ok) if tagged else []
        tag_str = ("  " + " ".join(tags)) if tags else ""
        top = " → top pick" if rank == 1 and not tags else ""

        typer.echo("")
        typer.secho(
            f"{rank}. {tool.display_name} {tool.marker}: {tool.mechanism}, "
            f"{tool.overhead_label()}{tag_str}{top}",
            bold=True,
        )
        typer.echo(f"   {tool.url}")
        if command is None:
            typer.secho(
                "   (no command: this tool can't handle this target)",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.secho(f"   $ {command}", fg=typer.colors.GREEN)
            follow = tool.follow_up(view, output)
            if follow:
                typer.secho(f"   $ {follow}", fg=typer.colors.GREEN, dim=True)
        viz_label, data_label = tool.views_label()
        if viz_label:
            typer.echo(f"   view directly: {viz_label}")
        if data_label:
            typer.echo(f"   data formats: {data_label}")
        for formats in tool.views.values():
            for fmt in formats:
                if catalog.FORMATS[fmt].kind == "data":
                    data_formats.setdefault(fmt, catalog.FORMATS[fmt].blurb)
        for note in tool.notes:
            typer.echo(f"   • {note}")
        if tool.install_hint:
            typer.echo(f"   • install: {tool.install_hint}")
        for msg in preflight.preflight_for(tool, attach):
            fg = typer.colors.RED if msg.startswith("⚠") else typer.colors.BRIGHT_BLACK
            typer.secho(f"   {msg}", fg=fg)

    if data_formats:
        typer.echo("")
        typer.secho("Data Format Viewers:", bold=True)
        width = max(len(name) for name in data_formats)
        for name, blurb in data_formats.items():
            typer.echo(f"   {name:<{width}}  {blurb}")

    return built


def _maybe_run(
    built: list[tuple[Tool, str | None]],
    *,
    run: bool,
    target: str | None,
    attach: bool,
) -> None:
    """Execute the top command, gated behind confirmation."""
    if not run or not built:
        return
    tool, command = built[0]
    if command is None:
        typer.secho(
            f"\n{tool.display_name} has no runnable command for this target.",
            fg=typer.colors.YELLOW,
        )
        return
    block = preflight.preflight_blocks_run(tool, attach)
    if block:
        typer.secho(f"\nNot running. {block}", fg=typer.colors.RED)
        return
    # A target passed alongside --run is consent to run immediately;
    # otherwise ask, defaulting to No.
    if not target:
        if not typer.confirm(
            f"\nRun the top command for {tool.display_name}?", default=False
        ):
            return
    typer.secho(f"\n$ {command}", fg=typer.colors.GREEN)
    # shell=True: recipes carry env-var prefixes (PYTHONPERFSUPPORT=1) and a
    # `--` separator a naive split would mangle. Only the single top recipe
    # the user explicitly opted into is ever executed.
    subprocess.run(command, shell=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def _command(
    ctx: typer.Context,
    all_: bool = typer.Option(
        False,
        "--all",
        help="Show the full landscape (incompatible tools tagged, not hidden).",
    ),
    focus: str | None = typer.Option(
        None, "--focus", help="any | time | memory | both."
    ),
    tool_key: str | None = typer.Option(
        None,
        "--tool",
        help="Show exactly this tool (bypasses focus/version/platform filters).",
    ),
    pid: int | None = typer.Option(
        None, "--pid", help="Attach to this PID (attach-capable tools only)."
    ),
    python: str | None = typer.Option(
        None,
        "--python",
        help="Target interpreter X.Y, or 'any' to disable version filtering.",
    ),
    lowest_overhead: bool = typer.Option(
        False, "--lowest-overhead", help="Keep prod-safe samplers (py-spy, Tachyon)."
    ),
    stdlib_only: bool = typer.Option(
        False, "--stdlib-only", help="Keep tools that ship in CPython."
    ),
    native: bool = typer.Option(
        False, "--native", help="Keep tools with native-frame support."
    ),
    view: str | None = typer.Option(
        None, "--view", help="flamegraph | call-tree | timeline | line | stats."
    ),
    rate: int | None = typer.Option(
        None, "--rate", help="Sampling rate in Hz (adjusts samplers that take a rate)."
    ),
    output: str | None = typer.Option(
        None, "--output", help="Output file path for the recipe."
    ),
    run: bool = typer.Option(
        False,
        "--run",
        help="Run the top command (opt-in, asks first without a target).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Machine-readable output (no prompts)."
    ),
    nosy: bool = typer.Option(
        False,
        "--nosy",
        help="Also ask about python version, attach, native, rate and view.",
    ),
) -> None:
    """Which profiler, when? Filter the roster, rank by measured overhead."""
    if nosy and json_output:
        raise typer.BadParameter(
            "--nosy asks interactive questions; it can't be combined with --json."
        )
    if focus is not None and focus not in catalog.FOCUS_CHOICES:
        raise typer.BadParameter(
            f"--focus must be one of {catalog.FOCUS_CHOICES}, got {focus!r}"
        )
    if view is not None and view not in catalog.VIEW_CHOICES:
        raise typer.BadParameter(
            f"--view must be one of {catalog.VIEW_CHOICES}, got {view!r}"
        )
    if tool_key is not None:
        # Users type the display name's hyphen (py-spy); keys use underscores.
        tool_key = tool_key.replace("-", "_")
    if tool_key is not None and tool_key not in catalog.BY_KEY:
        raise typer.BadParameter(
            f"--tool must be one of {sorted(catalog.BY_KEY)}, got {tool_key!r}"
        )

    target = " ".join(ctx.args) if ctx.args else None
    if _target_looks_duplicated(target):
        raise typer.BadParameter(
            f"ambiguous target {target!r}; looks like a bare argument was combined "
            "with a `--` target (e.g. `which-profiler typer --tool scalene -- python "
            "-m typer`). Pass the target only once, after `--`."
        )
    mode = "attach" if pid is not None else ("launch" if target else None)

    interactive = not (
        json_output
        or all_
        or focus is not None
        or pid is not None
        or tool_key is not None
        or target
    )
    if json_output and not (
        focus is not None or pid is not None or all_ or tool_key is not None
    ):
        raise typer.BadParameter(
            "--json needs at least one of --focus, --pid, --tool or --all "
            "(no prompts in json mode)."
        )

    if interactive and focus is None:
        focus = _ask_focus()

    if nosy:
        # Ask about the same knobs normally only reachable via flags.
        if python is None:
            python = _ask_python()
        if pid is None and not target:
            pid = _ask_attach()
            mode = "attach" if pid is not None else mode
        if not native:
            native = _ask_native()
        if rate is None:
            rate = _ask_rate()
        if view is None:
            view = _ask_view()

    target_py = _parse_python(python) if python is not None else _detected_python()
    python_overridden = python is not None

    if not json_output:
        if target_py is None:
            typer.secho(
                "python version filter disabled (--python any).",
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            source = "target" if python_overridden else "detected"
            typer.secho(
                f"{source} python {target_py[0]}.{target_py[1]}, filtering "
                "(--python X.Y to correct, --python any to disable version filtering).",
                fg=typer.colors.BRIGHT_BLACK,
            )
        typer.secho("⏱ = time  💾 = memory", fg=typer.colors.BRIGHT_BLACK)

    attach = mode == "attach"
    trampoline_ok = preflight.has_perf_trampoline()

    if tool_key is not None:
        # --tool wins over focus/version/platform filters; incompatibilities
        # are tagged, not hidden.
        survivors = [catalog.BY_KEY[tool_key]]
        tagged = True
    else:
        survivors = catalog.filter_tools(
            focus=focus,
            mode=mode,
            lowest_overhead=lowest_overhead,
            stdlib_only=stdlib_only,
            native=native,
            view=view,
            target_py=target_py,
            platform=sys.platform,
            show_all=all_,
        )
        if not all_ and not trampoline_ok:
            survivors = [t for t in survivors if t.key != "perf"]
        tagged = all_

    if json_output:
        records = []
        for rank, tool in enumerate(survivors, start=1):
            command = tool.build_command(
                target=target,
                pid=pid,
                native=native,
                rate=rate,
                view=view,
                output=output,
            )
            records.append(_rec_dict(tool, rank, command, view, output))
        payload = {
            "filters": {
                "focus": focus,
                "mode": mode,
                "pid": pid,
                "tool": tool_key,
                "python": f"{target_py[0]}.{target_py[1]}" if target_py else "any",
                "platform": sys.platform,
                "lowest_overhead": lowest_overhead,
                "stdlib_only": stdlib_only,
                "native": native,
                "view": view,
                "rate": rate,
                "all": all_,
                "target": target,
            },
            "results": records,
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    if not survivors:
        typer.secho(
            "\nNo profiler matches those filters; loosen one (drop --view/--native, "
            "or try --all).",
            fg=typer.colors.YELLOW,
        )
        return

    built = _render(
        survivors,
        target=target,
        pid=pid,
        native=native,
        rate=rate,
        view=view,
        output=output,
        attach=attach,
        target_py=target_py,
        trampoline_ok=trampoline_ok,
        tagged=tagged,
    )
    if python_overridden and any(t.requires or t.attach for t, _ in built):
        typer.secho(
            "\nnote: permission/build checks describe the interpreter running "
            "which-profiler; they may not apply to the --python target.",
            fg=typer.colors.BRIGHT_BLACK,
        )
    _maybe_run(built, run=run, target=target, attach=attach)


def main() -> None:
    """Console-script entry point (``which_profiler:main``); runs the typer app."""
    app()
