"""CLI surface: json, passthrough, --tool, interactive, preflight."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import pytest
from typer.testing import CliRunner

from which_profiler import preflight
from which_profiler.catalog import BY_KEY
from which_profiler.cli import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI color codes so substring checks survive Rich highlighting.

    With color on (e.g. CI's FORCE_COLOR), Rich highlights option names and
    splits ``--nosy`` into ``-`` + ``-nosy`` with escape codes between the
    dashes, breaking a naive ``"--nosy" in output`` check.
    """
    return _ANSI.sub("", text)


@pytest.fixture(autouse=True)
def _trampoline_ok(monkeypatch):
    """Make perf visibility deterministic regardless of the test interpreter."""
    monkeypatch.setattr(preflight, "has_perf_trampoline", lambda: True)


def _json(*args: str) -> dict[str, Any]:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return dict(json.loads(result.output))


def test_json_focus_time_valid_and_ranked() -> None:
    payload = _json("--focus", "time", "--json", "--python", "3.15")
    keys = [r["key"] for r in payload["results"]]
    assert keys[0] == "tachyon"
    first = payload["results"][0]
    assert set(first) >= {
        "key",
        "display_name",
        "rank",
        "marker",
        "mechanism",
        "command",
        "python_min",
        "platforms",
        "views",
        "notes",
        "overhead_category",
        "overhead_driver",
        "focus",
        "stdlib",
        "attach",
        "native",
        "requires",
        "install_hint",
        "url",
    }
    # Only the coarse category is exposed; exact ratios stay in the
    # profiler-landscape dataset, not in any CLI output.
    assert first["overhead_category"] == "negligible"
    assert "overhead" not in first
    assert payload["filters"]["focus"] == "time"


def test_json_requires_a_selector() -> None:
    result = runner.invoke(app, ["--json"])
    assert result.exit_code != 0
    assert "json" in result.output.lower()


def test_json_focus_both_is_scalene_only() -> None:
    payload = _json("--focus", "both", "--json")
    assert [r["key"] for r in payload["results"]] == ["scalene"]


def test_json_pid_keeps_attach_tools() -> None:
    payload = _json("--pid", "1234", "--python", "3.15", "--json")
    keys = {r["key"] for r in payload["results"]}
    # memray and viztracer are also attach-capable (`memray attach <PID>`,
    # `viztracer --attach <PID>`) alongside the samplers.
    assert keys == {"py_spy", "tachyon", "memray", "viztracer"}
    cmds = {r["key"]: r["command"] for r in payload["results"]}
    assert (
        cmds["py_spy"] == "uvx py-spy record -r 100 -o out.svg --pid 1234 --duration 30"
    )
    assert cmds["memray"] == "uv run --with memray memray attach -o out.bin 1234"


def test_python_310_hides_tachyon_and_perf() -> None:
    payload = _json("--focus", "time", "--python", "3.10", "--json")
    keys = {r["key"] for r in payload["results"]}
    assert "tachyon" not in keys and "perf" not in keys


def test_python_any_disables_version_filter() -> None:
    payload = _json("--focus", "time", "--python", "any", "--json")
    keys = {r["key"] for r in payload["results"]}
    assert "tachyon" in keys
    assert payload["filters"]["python"] == "any"


def test_python_any_case_insensitive() -> None:
    payload = _json("--focus", "time", "--python", "ANY", "--json")
    assert payload["filters"]["python"] == "any"


def test_passthrough_forms_are_equivalent() -> None:
    # Bare "typer" (with or without a leading "--") is an ambiguous console
    # script on $PATH; resolved via $(which ...) at shell run-time, never
    # assumed to be an importable module.
    for argv in (
        ["--focus", "time", "--python", "3.15", "--json", "typer"],
        ["--focus", "time", "--python", "3.15", "--json", "--", "typer"],
    ):
        payload = _json(*argv)
        cmds = {r["key"]: r["command"] for r in payload["results"]}
        assert cmds["py_spy"] == (
            "uv run --with py-spy py-spy record -r 100 -o out.svg -- python $(which typer)"
        )
        assert (
            cmds["cprofile"] == "uv run python -m cProfile -o out.pstats $(which typer)"
        )

    # An explicit "-m typer" is a different, unambiguous request and must
    # build a real "-m typer" invocation instead.
    payload = _json(
        "--focus", "time", "--python", "3.15", "--json", "python", "-m", "typer"
    )
    cmds = {r["key"]: r["command"] for r in payload["results"]}
    assert cmds["py_spy"] == (
        "uv run --with py-spy py-spy record -r 100 -o out.svg -- python -m typer"
    )
    assert cmds["cprofile"] == "uv run python -m cProfile -o out.pstats -m typer"


def test_passthrough_script_with_args() -> None:
    payload = _json("--focus", "memory", "--json", "--", "bench.py", "--n", "5")
    scalene = next(r for r in payload["results"] if r["key"] == "scalene")
    assert (
        scalene["command"]
        == "uv run --with scalene scalene run -o out.json bench.py --n 5"
    )


def test_scalene_module_target_uses_runpy_shim() -> None:
    # scalene `run` only accepts a script path (no `-m`), so a module target
    # gets a generated runpy shim instead of a missing/broken command.
    payload = _json("--focus", "memory", "--json", "--", "python", "-m", "my_module")
    scalene = next(r for r in payload["results"] if r["key"] == "scalene")
    assert scalene["command"] == (
        'printf \'import runpy\\nrunpy.run_module("my_module", '
        'run_name="__main__")\\n\' > _scalene_shim_my_module.py && '
        "uv run --with scalene scalene run -o out.json _scalene_shim_my_module.py"
    )


def test_tool_selector_bypasses_filters() -> None:
    # tachyon survives --tool despite a 3.10 version filter; tagged instead.
    payload = _json("--tool", "tachyon", "--python", "3.10", "--json")
    assert [r["key"] for r in payload["results"]] == ["tachyon"]
    result = runner.invoke(app, ["--tool", "tachyon", "--python", "3.10"])
    assert result.exit_code == 0, result.output
    assert "[needs 3.15+]" in result.output


def test_tool_selector_with_target() -> None:
    payload = _json("--tool", "py_spy", "--json", "--", "typer")
    assert payload["results"][0]["command"] == (
        "uv run --with py-spy py-spy record -r 100 -o out.svg -- python $(which typer)"
    )


def test_ambiguous_bare_arg_plus_dash_target_is_rejected() -> None:
    # `which-profiler typer --tool scalene -- python -m typer`; click glues
    # the stray "typer" positional onto the `--` target, producing a
    # nonsensical "typer python -m typer" command. Must error, not build it.
    result = runner.invoke(
        app, ["typer", "--tool", "scalene", "--", "python", "-m", "typer"]
    )
    assert result.exit_code != 0
    assert "ambiguous target" in result.output


def test_tool_selector_accepts_hyphenated_name() -> None:
    # The display name is "py-spy"; the key is "py_spy". Accept both.
    payload = _json("--tool", "py-spy", "--json")
    assert [r["key"] for r in payload["results"]] == ["py_spy"]


def test_tool_selector_rejects_unknown() -> None:
    result = runner.invoke(app, ["--tool", "nosuch"])
    assert result.exit_code != 0


def test_all_tags_instead_of_hiding() -> None:
    result = runner.invoke(app, ["--all", "--python", "3.10"])
    assert result.exit_code == 0, result.output
    assert "[needs 3.15+]" in result.output
    assert "Tachyon" in result.output


def test_no_confirm_prompt_and_hint_line() -> None:
    result = runner.invoke(app, ["--focus", "time"])
    assert result.exit_code == 0, result.output
    assert "?" not in result.output.split("\n")[0]
    assert "--python any to disable version filtering" in result.output


def test_perf_hidden_without_trampoline(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "has_perf_trampoline", lambda: False)
    payload = _json("--focus", "time", "--python", "3.14", "--json")
    assert "perf" not in {r["key"] for r in payload["results"]}
    # --all tags it instead.
    result = runner.invoke(app, ["--all", "--python", "3.14"])
    assert "[no perf trampoline in this build]" in result.output


def test_human_output_shows_new_fields() -> None:
    result = runner.invoke(app, ["--focus", "time", "--python", "3.15"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "→ top pick" in out
    assert "⏱ = time  💾 = memory" in out  # marker legend
    assert "view directly: flamegraph (html), line (heatmap)" in out  # tachyon
    assert (
        "data formats: flamegraph (collapsed), call-tree (pstats), timeline (gecko)"
        in out
    )  # tachyon
    assert "sampling, out-of-process" in out
    assert "overhead: negligible" in out
    assert "https://github.com/benfred/py-spy" in out
    assert "1.01" not in out  # exact ratios never leave the dataset
    # Footer legend explains every data format that appeared, once.
    assert "Data Format Viewers:" in out
    assert out.count("https://www.speedscope.app") == 1
    assert "https://profiler.firefox.com" in out


def test_interactive_single_question() -> None:
    result = runner.invoke(app, [], input="2\n")
    assert result.exit_code == 0, result.output
    assert "What do you care about?" in result.output
    assert result.output.count("choice") == 1  # exactly one question
    assert "py-spy" in result.output


def test_nosy_asks_five_extra_questions() -> None:
    # order: focus, python, attach, native, rate, view.
    result = runner.invoke(app, ["--nosy"], input="2\n3.15\nn\nn\n50\n1\n")
    assert result.exit_code == 0, result.output
    assert "What do you care about?" in result.output
    assert "Target python version" in result.output
    assert "Attach to a running process" in result.output
    assert "Keep only tools with native-frame support" in result.output
    assert "Sampling rate in Hz" in result.output
    assert "Preferred view?" in result.output
    assert "flamegraph" in result.output.lower()  # view=1 -> flamegraph applied
    assert "-r 50" in result.output or "50" in result.output  # rate applied somewhere


def test_nosy_rejects_json() -> None:
    result = runner.invoke(app, ["--nosy", "--json", "--all"])
    assert result.exit_code != 0
    assert "--nosy" in _plain(result.output)


def test_nosy_skips_questions_already_answered_by_flags() -> None:
    result = runner.invoke(
        app,
        [
            "--nosy",
            "--python",
            "any",
            "--native",
            "--view",
            "flamegraph",
            "--rate",
            "42",
        ],
        input="2\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "What do you care about?" in result.output
    assert "Target python version" not in result.output
    assert "Attach to a running process" in result.output  # pid still unset -> asked
    assert "Keep only tools with native-frame support" not in result.output
    assert "Sampling rate in Hz" not in result.output
    assert "Preferred view?" not in result.output


def test_preflight_inline_and_modes(monkeypatch) -> None:
    def fake_read_int(path: str):
        if path == preflight.PTRACE_SCOPE_PATH:
            return 2
        if path == preflight.PERF_PARANOID_PATH:
            return 3
        return None

    monkeypatch.setattr(preflight, "_read_int", fake_read_int)

    msgs = preflight.preflight_for(BY_KEY["py_spy"], attach=True)
    assert any("ptrace_scope is 2" in m for m in msgs)
    assert preflight.preflight_for(BY_KEY["py_spy"], attach=False) == []

    msgs = preflight.preflight_for(BY_KEY["perf"], attach=False)
    assert any("perf_event_paranoid is 3, needs ≤ 1" in m for m in msgs)


def test_preflight_renders_on_the_entry(monkeypatch) -> None:
    monkeypatch.setattr(
        preflight,
        "_read_int",
        lambda path: 3 if path == preflight.PERF_PARANOID_PATH else 0,
    )
    result = runner.invoke(app, ["--tool", "perf"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    warn_idx = next(i for i, ln in enumerate(lines) if "perf_event_paranoid is 3" in ln)
    title_idx = next(
        i for i, ln in enumerate(lines) if ln.lstrip().startswith("1. perf")
    )
    assert warn_idx > title_idx  # inline under the perf entry, not a global block


def test_preflight_missing_proc_is_a_note(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_read_int", lambda path: None)
    msgs = preflight.preflight_for(BY_KEY["py_spy"], attach=True)
    assert msgs and all(m.startswith("note:") for m in msgs)


def test_macos_attach_note(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_read_int", lambda path: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    msgs = preflight.preflight_for(BY_KEY["py_spy"], attach=True)
    assert any("sudo on macOS" in m for m in msgs)


def test_frame_pointer_notes(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "has_frame_pointers", lambda: True)
    assert "Python frames resolve" in preflight.frame_pointer_note()
    monkeypatch.setattr(preflight, "has_frame_pointers", lambda: False)
    assert "-X perf_jit" in preflight.frame_pointer_note()


def test_python_override_check_note() -> None:
    result = runner.invoke(app, ["--focus", "time", "--python", "3.15"])
    assert "may not apply to the --python target" in result.output
