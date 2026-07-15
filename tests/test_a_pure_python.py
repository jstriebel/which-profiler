"""Runs ``a_pure_python.py`` from the image-analysis example arc directly.

That script is stdlib-only (no numpy/h5py/etc.), so unlike the rest of the
example arc it doesn't need the ``examples/image_analysis`` project's venv,
it runs under this repo's own dev environment, including on CPython 3.15
where the rest of the arc has no wheels yet. Fixture CSVs are written by
hand here (not via ``generate_data.py``) to keep this test numpy-free too.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "image_analysis"


def _load_a_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "a_pure_python", EXAMPLES_DIR / "a_pure_python.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_tiny_csvs(folder: Path) -> None:
    """A 2x2 pixel grid, one per-class probability CSV, no numpy involved."""
    folder.mkdir(parents=True, exist_ok=True)
    # Class 0 wins top-left, class 2 wins the rest, so the colorcode isn't trivial.
    per_class_rows = {
        0: ["0.7 0.1", "0.1 0.1"],
        1: ["0.1 0.2", "0.2 0.2"],
        2: ["0.1 0.6", "0.6 0.6"],
        3: ["0.1 0.1", "0.1 0.1"],
    }
    for class_id, rows in per_class_rows.items():
        (folder / f"{class_id}.csv").write_text("\n".join(rows) + "\n")


def test_a_pure_python_runs(tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    _write_tiny_csvs(data_dir)

    a_module = _load_a_module()
    colored = a_module.run(data_dir)

    assert len(colored) == 2 and len(colored[0]) == 2
    # Top-left pixel: class 0 (blue) wins with prob 0.7.
    assert colored[0][0] == [0 * 0.7, 0 * 0.7, 255 * 0.7]
    # Bottom-right pixel: class 2 (red) wins with prob 0.6.
    assert colored[1][1] == [255 * 0.6, 0 * 0.6, 0 * 0.6]

    err = capsys.readouterr().err
    assert "processed in" in err


def test_a_pure_python_has_no_third_party_imports() -> None:
    """Guard the whole point of this script: stdlib-only, so it runs on 3.15."""
    source = (EXAMPLES_DIR / "a_pure_python.py").read_text()
    stdlib_only = {"__future__", "argparse", "sys", "time", "pathlib"}
    for line in source.splitlines():
        line = line.strip()
        if line.startswith(("import ", "from ")):
            module = line.split()[1].split(".")[0]
            assert module in stdlib_only, f"non-stdlib import found: {line!r}"
    assert sys.version_info >= (
        3,
        10,
    )  # sanity: this test itself has no version ceiling
