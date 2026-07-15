"""Filter-pipeline behaviour: focus mapping, knobs, version + platform hiding."""

from __future__ import annotations

from which_profiler import catalog


def _keys(**kwargs) -> set[str]:
    return {t.key for t in catalog.filter_tools(**kwargs)}


def test_focus_any_is_unfiltered() -> None:
    assert _keys(focus="any") == set(catalog.BY_KEY)
    assert _keys(focus=None) == set(catalog.BY_KEY)


def test_focus_time_includes_mixed_tools() -> None:
    # scalene (time + memory) counts as a time profiler too.
    assert _keys(focus="time") == {
        "cprofile",
        "pyinstrument",
        "py_spy",
        "tachyon",
        "scalene",
        "viztracer",
        "perf",
    }


def test_focus_memory() -> None:
    assert _keys(focus="memory") == {"memray", "scalene"}


def test_focus_both_is_scalene_only() -> None:
    assert _keys(focus="both") == {"scalene"}


def test_attach_mode_keeps_only_attach_tools() -> None:
    # memray documents `memray attach <PID>` (gdb/lldb injection); viztracer
    # documents `viztracer --attach <PID>` (gdb/lldb injection too); perf is
    # launch-only for Python frames, so it is NOT attach-capable here.
    assert _keys(mode="attach") == {"py_spy", "tachyon", "memray", "viztracer"}


def test_lowest_overhead() -> None:
    assert _keys(focus="time", lowest_overhead=True) == {"py_spy", "tachyon"}


def test_stdlib_only() -> None:
    assert _keys(stdlib_only=True) == {"cprofile", "tachyon"}


def test_native_filter() -> None:
    assert _keys(focus="time", native=True) == {"py_spy", "tachyon", "perf", "scalene"}
    # scalene (native=True: per-line Python-vs-C split) shows under memory too.
    assert _keys(focus="memory", native=True) == {"memray", "scalene"}


def test_view_flamegraph() -> None:
    assert _keys(view="flamegraph") == {
        "py_spy",
        "tachyon",
        "perf",
        "memray",
        "pyinstrument",
    }


def test_view_call_tree() -> None:
    assert _keys(view="call-tree") == {"pyinstrument", "tachyon", "memray", "perf"}


def test_view_timeline_and_line() -> None:
    assert _keys(view="timeline") == {"viztracer", "tachyon"}
    assert _keys(view="line") == {"scalene", "tachyon"}


def test_python_310_hides_tachyon_and_perf() -> None:
    keys = _keys(target_py=(3, 10))
    assert "tachyon" not in keys
    assert "perf" not in keys
    assert "cprofile" in keys


def test_python_none_disables_version_filter() -> None:
    assert "tachyon" in _keys(target_py=None)


def test_platform_filter() -> None:
    win = _keys(platform="win32")
    assert "perf" not in win and "memray" not in win
    mac = _keys(platform="darwin")
    assert "memray" in mac and "perf" not in mac
    linux = _keys(platform="linux")
    assert {"perf", "memray"} <= linux


def test_show_all_skips_version_and_platform_hiding() -> None:
    keys = _keys(target_py=(3, 10), platform="win32", show_all=True)
    assert {"tachyon", "perf", "memray"} <= keys


def test_ranking_order_by_call_heavy() -> None:
    ranked = catalog.filter_tools(focus="time")
    assert [t.key for t in ranked] == [
        "tachyon",
        "py_spy",
        "perf",
        "scalene",
        "pyinstrument",
        "viztracer",
        "cprofile",
    ]
