"""Permission and capability preflight (REPORT ONLY).

Checks are rendered inline on the affected catalog entry. This module never
mutates a sysctl, never escalates, and never executes a fix: it reads
``/proc``, ``os.geteuid()`` and ``sysconfig``, and returns strings. Missing
``/proc`` files (non-Linux) yield a note, not a failure.
"""

from __future__ import annotations

import pathlib
import sys
import sysconfig

from .catalog import Tool

PTRACE_SCOPE_PATH = "/proc/sys/kernel/yama/ptrace_scope"
PERF_PARANOID_PATH = "/proc/sys/kernel/perf_event_paranoid"


def _read_int(path: str) -> int | None:
    try:
        with pathlib.Path(path).open(encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def check_ptrace() -> str | None:
    scope = _read_int(PTRACE_SCOPE_PATH)
    if scope is None:
        if sys.platform == "darwin":
            return "note: attach needs sudo on macOS"
        return (
            "note: cannot read ptrace_scope (non-Linux?); attach permission unchecked"
        )
    if scope <= 1:
        return None
    return (
        f"⚠ ptrace_scope is {scope}, attach needs ≤ 1; "
        f"fix: echo 0 | sudo tee {PTRACE_SCOPE_PATH}"
    )


def check_perf_events() -> str | None:
    paranoid = _read_int(PERF_PARANOID_PATH)
    if paranoid is None:
        return (
            "note: cannot read perf_event_paranoid (non-Linux?); "
            "perf permission unchecked"
        )
    if paranoid <= 1:
        return None
    return (
        f"⚠ perf_event_paranoid is {paranoid}, needs ≤ 1; "
        f"fix: sudo sysctl kernel.perf_event_paranoid=1"
    )


def has_perf_trampoline() -> bool:
    """Whether THIS interpreter's build supports the perf trampoline.

    CPython spells the config var ``PY_HAVE_PERF_TRAMPOLINE`` in installed
    builds; check the bare name too for safety.
    """
    return bool(
        sysconfig.get_config_var("HAVE_PERF_TRAMPOLINE")
        or sysconfig.get_config_var("PY_HAVE_PERF_TRAMPOLINE")
    )


def has_frame_pointers() -> bool:
    """Whether THIS interpreter was compiled with ``-fno-omit-frame-pointer``.

    Distinct from the trampoline: the trampoline emits the frames, frame
    pointers let perf's unwinder walk them.
    """
    cflags = sysconfig.get_config_var("CFLAGS") or ""
    return "-fno-omit-frame-pointer" in cflags


def frame_pointer_note() -> str:
    if has_frame_pointers():
        return "note: frame-pointer build; Python frames resolve in perf output"
    return (
        "note: no frame pointers recorded in this build's CFLAGS; "
        "add -X perf_jit (perf ≥ 6.8)"
    )


def preflight_for(tool: Tool, attach: bool) -> list[str]:
    """Inline messages for ``tool``; ``⚠`` entries are blocking, notes are not."""
    messages: list[str] = []
    if attach and tool.attach:
        msg = check_ptrace()
        if msg:
            messages.append(msg)
    if tool.requires == "perf_events":
        msg = check_perf_events()
        if msg:
            messages.append(msg)
        messages.append(frame_pointer_note())
    return messages


def preflight_blocks_run(tool: Tool, attach: bool) -> str | None:
    """The blocking warning if ``--run`` must be refused, else ``None``."""
    for msg in preflight_for(tool, attach):
        if msg.startswith("⚠"):
            return msg
    return None
