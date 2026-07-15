# Step C: HDF5 load + naive numpy colorcode.

# I/O is fixed (HDF5 instead of CSV), so the hotspot moves to compute: the
# naive colorcode recomputes the max, works in float64, and allocates several
# full-size temporaries; a memory-aware line profiler (scalene) shows where.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import numpy as np


def load_probabilities(folder: Path) -> np.ndarray:
    with h5py.File(folder / "data.hdf5", "r") as f:
        return f["probabilities"][:]


def colorcode_probabilities(probabilities: np.ndarray) -> np.ndarray:
    predicted_classes = np.argmax(probabilities, axis=2)
    max_prob = np.max(probabilities, axis=2)
    class_colors = np.array(
        [[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]], dtype=np.uint8
    )
    colored_probabilities = class_colors[predicted_classes]
    colored_probabilities = colored_probabilities * max_prob[..., np.newaxis]
    return colored_probabilities.astype(np.uint8)


def load_and_colorcode_probabilities(folder: Path) -> np.ndarray:
    probabilities = load_probabilities(folder)
    return colorcode_probabilities(probabilities)


def run(data: Path) -> np.ndarray:
    t0 = time.perf_counter()
    colored_probabilities = load_and_colorcode_probabilities(data)

    # Keep the hot call clear of the timer line, since some line profilers bill
    # trailing C time to the next executed line.
    _ = colored_probabilities

    t1 = time.perf_counter()
    print(f"processed in {t1 - t0:.2f}s", file=sys.stderr)
    return colored_probabilities


def _resolve_data(value: str) -> Path:
    """Accept a bare size key (s/m/l) as shorthand for the sibling data dir, or any path."""
    return (
        Path(__file__).parent / "data" / value
        if value in ("s", "m", "l")
        else Path(value)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=_resolve_data,
        default="s",
        help="size key (s/m/l) or a data folder path",
    )
    args = parser.parse_args(argv)
    run(args.data)


if __name__ == "__main__":
    main()
