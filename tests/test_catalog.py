"""Catalog integrity, target parsing, and command-building contracts."""

from __future__ import annotations

import pytest

from which_profiler import catalog
from which_profiler.catalog import BY_KEY, CATALOG, Tool, parse_target


def test_roster_is_the_expected_keys() -> None:
    assert set(BY_KEY) == {
        "cprofile",
        "pyinstrument",
        "py_spy",
        "tachyon",
        "scalene",
        "memray",
        "viztracer",
        "perf",
    }


def test_overhead_exact_values() -> None:
    expected = {
        "tachyon": (0.99, 1.01),
        "py_spy": (1.05, 1.10),
        "perf": (1.02, 1.21),
        "memray": (1.03, 2.34),
        "pyinstrument": (1.00, 2.48),
        "viztracer": (1.00, 2.48),
        "cprofile": (1.02, 2.91),
        "scalene": (1.51, 1.63),
    }
    for key, (cpu, call) in expected.items():
        assert BY_KEY[key].overhead == {"cpu_bound": cpu, "call_heavy": call}


def test_overhead_coarse_labels() -> None:
    assert BY_KEY["tachyon"].overhead_label() == "overhead: negligible"
    assert BY_KEY["py_spy"].overhead_label() == "overhead: negligible"
    assert BY_KEY["perf"].overhead_label() == "overhead: low"
    assert BY_KEY["scalene"].overhead_label() == "overhead: moderate"
    assert (
        BY_KEY["memray"].overhead_label() == "overhead: high (on allocation-heavy code)"
    )
    assert (
        BY_KEY["pyinstrument"].overhead_label() == "overhead: high (on call-heavy code)"
    )
    assert BY_KEY["viztracer"].overhead_label() == "overhead: high (on call-heavy code)"
    assert BY_KEY["cprofile"].overhead_label() == "overhead: high (on call-heavy code)"


def test_min_python_pins() -> None:
    assert BY_KEY["tachyon"].min_python == (3, 15)
    assert BY_KEY["perf"].min_python == (3, 12)


def test_platforms() -> None:
    assert BY_KEY["perf"].platforms == {"linux"}
    assert BY_KEY["memray"].platforms == {"linux", "darwin"}
    assert BY_KEY["py_spy"].platforms == {"linux", "darwin", "win32"}


def test_urls_and_markers_and_mechanisms() -> None:
    for tool in CATALOG:
        assert tool.url.startswith("https://")
        assert tool.marker in ("⏱", "💾", "⏱💾")
        assert tool.mechanism
    assert BY_KEY["scalene"].marker == "⏱💾"
    assert BY_KEY["memray"].marker == "💾"
    assert BY_KEY["py_spy"].mechanism == "sampling, out-of-process"
    assert BY_KEY["pyinstrument"].mechanism == "sampling, in-process"
    assert BY_KEY["cprofile"].mechanism == "tracing"
    assert BY_KEY["memray"].mechanism == "allocation tracing"


# --- target parsing rules ------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (None, ("script", "<your-script.py>", "")),
        ("", ("script", "<your-script.py>", "")),
        ("typer", ("script", "typer", "")),
        ("my.pkg", ("script", "my.pkg", "")),
        ("python -m typer", ("module", "typer", "")),
        ("python3 -m typer --help", ("module", "typer", "--help")),
        (
            "python3.12 -m my_module --input big.tif",
            ("module", "my_module", "--input big.tif"),
        ),
        ("-m typer", ("module", "typer", "")),
        ("script.py --arg", ("script", "script.py", "--arg")),
        ("python script.py --arg v", ("script", "script.py", "--arg v")),
        ("path/to/tool", ("script", "path/to/tool", "")),
        (
            "mycmd --flag",
            ("script", "mycmd", "--flag"),
        ),  # multi-token non-.py -> command form
        ("python", ("script", "<your-script.py>", "")),
    ],
)
def test_parse_target(target, expected) -> None:
    assert parse_target(target) == expected


# --- command building ------------------------------------------------------------


@pytest.mark.parametrize("tool", CATALOG, ids=lambda t: t.key)
def test_every_tool_builds_with_and_without_target(tool: Tool) -> None:
    placeholder = tool.build_command(target=None)
    concrete = tool.build_command(target="python myscript.py --input big.tif")
    assert placeholder is not None
    assert concrete is not None
    assert "myscript.py" in concrete
    assert "big.tif" in concrete


@pytest.mark.parametrize("tool", CATALOG, ids=lambda t: t.key)
def test_placeholder_passes_through_unresolved(tool: Tool) -> None:
    # The no-target placeholder is a template for the user to fill in, not a
    # real name; it must never get wrapped in `$(which ...)` (it doesn't
    # literally end in ".py", it ends in ".py>", so a naive suffix check
    # would otherwise treat it as a bare console-script word).
    placeholder = tool.build_command(target=None)
    assert placeholder is not None
    assert "<your-script.py>" in placeholder
    assert "which" not in placeholder


@pytest.mark.parametrize("tool", CATALOG, ids=lambda t: t.key)
def test_real_path_target_is_not_treated_as_module(tool: Tool) -> None:
    # An existing (or plausible) file path must be passed straight through:
    # never turned into a `-m ...` module invocation and never wrapped in
    # `$(which ...)` (which is only for bare, path-less console-script words).
    cmd = tool.build_command(target="examples/image_analysis/a_pure_python.py")
    assert cmd is not None
    assert "examples/image_analysis/a_pure_python.py" in cmd
    assert "-m examples" not in cmd
    assert "which" not in cmd


@pytest.mark.parametrize("tool", CATALOG, ids=lambda t: t.key)
def test_every_view_builds_a_valid_command(tool: Tool) -> None:
    for view in tool.views:
        cmd = tool.build_command(target="python myscript.py", view=view)
        assert cmd is not None and cmd.strip()


def test_uv_based_commands() -> None:
    # "typer" is a bare word, an ambiguous console-script on $PATH, so it's
    # resolved with $(which ...) at shell run-time rather than assumed to be
    # an importable module.
    assert BY_KEY["cprofile"].build_command(target="typer") == (
        "uv run python -m cProfile -o out.pstats $(which typer)"
    )
    assert BY_KEY["pyinstrument"].build_command(target="typer") == (
        "uv run --with pyinstrument pyinstrument -o out.html $(which typer)"
    )
    assert BY_KEY["py_spy"].build_command(target="typer") == (
        "uv run --with py-spy py-spy record -r 100 -o out.svg -- python $(which typer)"
    )
    assert BY_KEY["tachyon"].build_command(target="typer") == (
        "uv run --python 3.15 python -m profiling.sampling run -r 100 --flamegraph -o out.html $(which typer)"
    )
    assert BY_KEY["scalene"].build_command(target="script.py") == (
        "uv run --with scalene scalene run -o out.json script.py"
    )
    assert BY_KEY["memray"].build_command(target="typer") == (
        "uv run --with memray memray run -o out.bin $(which typer)"
    )
    assert BY_KEY["viztracer"].build_command(target="typer") == (
        "uv run --with viztracer viztracer -o out.html $(which typer)"
    )
    assert BY_KEY["perf"].build_command(target="typer") == (
        "PYTHONPERFSUPPORT=1 perf record -F 999 -g -- uv run python $(which typer)"
    )


def test_attach_commands() -> None:
    assert BY_KEY["py_spy"].build_command(pid=12345) == (
        "uvx py-spy record -r 100 -o out.svg --pid 12345 --duration 30"
    )
    assert BY_KEY["tachyon"].build_command(pid=12345) == (
        "uv run --python 3.15 python -m profiling.sampling attach -r 100 --flamegraph -d 30 -o out.html 12345"
    )
    assert BY_KEY["viztracer"].build_command(pid=12345) == (
        "uv run --with viztracer viztracer --attach 12345 -o out.html"
    )


def test_follow_ups() -> None:
    assert BY_KEY["cprofile"].follow_up() == "uv run python -m pstats out.pstats"
    assert (
        BY_KEY["memray"].follow_up() == "uv run --with memray memray flamegraph out.bin"
    )
    assert (
        BY_KEY["memray"].follow_up(view="stats")
        == "uv run --with memray memray stats out.bin"
    )
    assert (
        BY_KEY["memray"].follow_up(view="call-tree")
        == "uv run --with memray memray tree out.bin"
    )
    assert BY_KEY["perf"].follow_up() == "perf report -n -g --no-children"
    assert (
        BY_KEY["scalene"].follow_up()
        == "uv run --with scalene scalene view --html out.json"
    )
    assert BY_KEY["tachyon"].follow_up() is None
    assert (
        BY_KEY["tachyon"].follow_up(view="call-tree")
        == "uv run --python 3.15 python -m pstats out.pstats"
    )


def test_new_output_formats() -> None:
    # pyinstrument's flamegraph-equivalent is speedscope.
    assert BY_KEY["pyinstrument"].build_command(target="typer", view="flamegraph") == (
        "uv run --with pyinstrument pyinstrument -r speedscope -o out.speedscope.json $(which typer)"
    )
    # Tachyon's call-tree view emits cProfile-compatible pstats.
    assert BY_KEY["tachyon"].build_command(target="typer", view="call-tree") == (
        "uv run --python 3.15 python -m profiling.sampling run -r 100 --pstats -o out.pstats $(which typer)"
    )
    # memray's call-tree view is its terminal `tree` reporter (no capture-time flag change).
    assert BY_KEY["memray"].build_command(target="typer", view="call-tree") == (
        "uv run --with memray memray run -o out.bin $(which typer)"
    )
    # Tachyon's timeline view emits Firefox Profiler ("Gecko") JSON.
    assert BY_KEY["tachyon"].build_command(target="typer", view="timeline") == (
        "uv run --python 3.15 python -m profiling.sampling run -r 100 --gecko -o out.gecko.json $(which typer)"
    )
    # Tachyon's line view is a source-line heatmap (a directory, not a file).
    assert BY_KEY["tachyon"].build_command(target="typer", view="line") == (
        "uv run --python 3.15 python -m profiling.sampling run -r 100 --heatmap -o out_heatmap $(which typer)"
    )


def test_format_registry_covers_every_view() -> None:
    """Every format name used by any tool's views must be in FORMATS."""
    for tool in CATALOG:
        for formats in tool.views.values():
            for fmt in formats:
                assert fmt in catalog.FORMATS, f"{tool.key}: unknown format {fmt!r}"


def test_every_format_is_used_by_some_tool() -> None:
    """FORMATS must not accumulate orphan entries no tool references."""
    used = {
        fmt for tool in CATALOG for formats in tool.views.values() for fmt in formats
    }
    assert used == set(catalog.FORMATS)


def test_views_detailed_tags_data_vs_viz() -> None:
    detailed = {(d["view"], d["format"]): d for d in BY_KEY["tachyon"].views_detailed()}
    assert detailed[("flamegraph", "html")]["kind"] == "viz"
    assert detailed[("flamegraph", "collapsed")]["kind"] == "data"
    assert detailed[("timeline", "gecko")]["kind"] == "data"
    assert detailed[("line", "heatmap")]["kind"] == "viz"


def test_scalene_module_targets_get_runpy_shim() -> None:
    cmd = BY_KEY["scalene"].build_command(target="python -m my_module")
    assert cmd == (
        'printf \'import runpy\\nrunpy.run_module("my_module", '
        'run_name="__main__")\\n\' > _scalene_shim_my_module.py && '
        "uv run --with scalene scalene run -o out.json _scalene_shim_my_module.py"
    )
    assert BY_KEY["scalene"].build_command(target="bench.py") is not None


def test_scalene_bare_command_resolved_via_which() -> None:
    # A bare word like `typer` is an installed console-script on $PATH, not a
    # file relative to the cwd; scalene `run` needs an actual file path, so
    # it must be resolved with `$(which ...)` instead of passed verbatim
    # (which fails with FileNotFoundError since no such file exists).
    assert BY_KEY["scalene"].build_command(target="typer") == (
        "uv run --with scalene scalene run -o out.json $(which typer)"
    )
    assert BY_KEY["scalene"].build_command(target="mycmd --flag") == (
        "uv run --with scalene scalene run -o out.json $(which mycmd) --flag"
    )
    # Paths (with a "/") and ".py" files are left alone; they're already
    # real, resolvable file paths.
    assert BY_KEY["scalene"].build_command(target="path/to/tool") == (
        "uv run --with scalene scalene run -o out.json path/to/tool"
    )
    assert BY_KEY["scalene"].build_command(target="bench.py --n 5") == (
        "uv run --with scalene scalene run -o out.json bench.py --n 5"
    )


def test_native_knob() -> None:
    assert " -n " in f" {BY_KEY['py_spy'].build_command(target='x.py', native=True)} "
    tachyon_cmd = BY_KEY["tachyon"].build_command(target="x.py", native=True)
    assert tachyon_cmd is not None
    assert "--native" in tachyon_cmd
    memray_cmd = BY_KEY["memray"].build_command(target="x.py", native=True)
    assert memray_cmd is not None
    assert "--native" in memray_cmd


def test_rate_adjusts_samplers() -> None:
    py_spy_cmd = BY_KEY["py_spy"].build_command(target="x.py", rate=50)
    assert py_spy_cmd is not None
    assert "-r 50" in py_spy_cmd
    pyinstrument_cmd = BY_KEY["pyinstrument"].build_command(target="x.py", rate=100)
    assert pyinstrument_cmd is not None
    assert "-i 0.01" in pyinstrument_cmd
    tachyon_cmd = BY_KEY["tachyon"].build_command(target="x.py", rate=250)
    assert tachyon_cmd is not None
    assert "-r 250" in tachyon_cmd


def test_output_override() -> None:
    memray_cmd = BY_KEY["memray"].build_command(target="x.py", output="heap.bin")
    assert memray_cmd is not None
    assert "heap.bin" in memray_cmd


def test_ranking_is_ascending_by_call_heavy_with_none_last() -> None:
    ranked = catalog.rank(list(CATALOG))
    keys = [t.key for t in ranked]
    assert keys[0] == "tachyon"
    swept = [t.overhead for t in ranked if t.overhead is not None]
    ratios = [overhead["call_heavy"] for overhead in swept]
    assert ratios == sorted(ratios)
