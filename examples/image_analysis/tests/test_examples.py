"""End-to-end runs of the example-arc scripts against tiny generated data.

This is its own project (``examples/image_analysis/pyproject.toml``): run
with ``uv run --project examples/image_analysis pytest`` from the repo root,
or ``cd examples/image_analysis && uv run pytest``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent


def _importable(*modules: str) -> bool:
    probe = "; ".join(f"import {m}" for m in modules)
    return (
        subprocess.run([sys.executable, "-c", probe], capture_output=True).returncode
        == 0
    )


if not _importable("numpy", "h5py", "skimage", "sklearn"):
    pytest.skip(
        "examples deps not installed; run `uv run pytest` from examples/image_analysis",
        allow_module_level=True,
    )

_HAS_NUMBA = _importable("numba")


@pytest.fixture(scope="session")
def tiny_data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a small s-size dataset once for the whole session."""
    out = tmp_path_factory.mktemp("example-data")
    result = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_DIR / "generate_data.py"),
            "--crop-size",
            "100",
            "--sizes",
            "s",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert (out / "s" / "data.hdf5").exists()
    assert (out / "s" / "0.csv").exists()
    return out / "s"


def _run_step(script: str, tiny_data: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / script), "--data", str(tiny_data), *extra],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize(
    "script",
    [
        "a_pure_python.py",
        "b_csv_load.py",
        "c_hdf5_load.py",
        "d_dtypes.py",
        "e_chunked.py",
    ],
)
def test_step_runs(script: str, tiny_data: Path) -> None:
    result = _run_step(script, tiny_data)
    assert result.returncode == 0, result.stderr
    assert "processed in" in result.stderr


@pytest.mark.skipif(not _HAS_NUMBA, reason="numba not installed on this python")
def test_f_jit_runs(tiny_data: Path) -> None:
    result = _run_step("f_jit.py", tiny_data)
    assert result.returncode == 0, result.stderr
    assert "processed in" in result.stderr


def test_g_server_runs(tiny_data: Path) -> None:
    result = _run_step("g_server.py", tiny_data, "--duration", "1")
    assert result.returncode == 0, result.stderr
    assert "READY pid=" in result.stderr
    assert "requests served:" in result.stderr
