# Step D: HDF5 load + dtype-optimized numpy colorcode.

# Same pipeline as C with right-sized dtypes: uint8 class indices, argmax
# result reused instead of a max recompute, float32, unrolled RGB channels.
# An allocation profiler (memray) shows the temporaries that disappeared.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import numpy as np

CLASS_COLORS = np.array(
    [[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]], dtype=np.uint8
)


def load_probabilities(folder: Path) -> np.ndarray:
    with h5py.File(folder / "data.hdf5", "r") as f:
        return f["probabilities"][:]


def colorcode_probabilities(probabilities: np.ndarray) -> np.ndarray:
    # Use uint8 to reference classes (we only have 4):
    predicted_classes = np.argmax(probabilities, axis=2).astype(np.uint8)
    # Do not re-compute max, use argmax result to index:
    max_prob = np.take_along_axis(
        probabilities, predicted_classes[..., None], axis=2
    ).squeeze()
    # Free the large array once it's no longer needed:
    del probabilities
    # Use float32 to save memory:
    max_prob = max_prob.astype(np.float32)
    colored_probabilities = CLASS_COLORS[predicted_classes]
    # Unroll RGB loop:
    colored_probabilities[:, :, 0] = colored_probabilities[:, :, 0] * max_prob
    colored_probabilities[:, :, 1] = colored_probabilities[:, :, 1] * max_prob
    colored_probabilities[:, :, 2] = colored_probabilities[:, :, 2] * max_prob
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
