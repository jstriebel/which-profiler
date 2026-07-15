# Step F: HDF5 load + numba-jitted colorcode.

# The jitted loop is opaque to pure-Python samplers (one caller line); native
# frame support costs extra and needs a frame-pointer build. Deliberately not
# warm-compiled: the first-call JIT compile dominating a naive timing IS the
# demo. Also a version-constraint story: numba wheels lag new CPythons.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import numba
import numpy as np


def load_probabilities(folder: Path) -> np.ndarray:
    with h5py.File(folder / "data.hdf5", "r") as f:
        return f["probabilities"][:]


@numba.njit([numba.uint8[:, :, :](numba.float64[:, :, :])])
def colorcode_probabilities(probabilities: np.ndarray) -> np.ndarray:
    class_colors = np.array(
        [[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]], dtype=np.uint8
    )
    x_len, y_len = probabilities.shape[:2]
    colored_probabilities = np.zeros((x_len, y_len, 3), dtype=np.uint8)
    for x in range(x_len):
        for y in range(y_len):
            class_index = 0
            max_prob = 0
            for i, prob in enumerate(probabilities[x, y]):
                if prob > max_prob:
                    max_prob = prob
                    class_index = i
            colored_probabilities[x, y, 0] = np.uint8(
                class_colors[class_index, 0] * max_prob
            )
            colored_probabilities[x, y, 1] = np.uint8(
                class_colors[class_index, 1] * max_prob
            )
            colored_probabilities[x, y, 2] = np.uint8(
                class_colors[class_index, 2] * max_prob
            )
    return colored_probabilities


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
