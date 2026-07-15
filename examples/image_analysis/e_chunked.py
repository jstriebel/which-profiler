# Step E: chunked HDF5 reading + per-tile colorcode.

# Processes the probability map in fixed-size tiles instead of loading it
# whole: peak memory collapses to one output array plus one chunk. A CPU-time
# profiler can't explain why this is faster; a memory-aware one can.

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import h5py
import numpy as np

CHUNK_SIZE = 1024

CLASS_COLORS = np.array(
    [[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]], dtype=np.uint8
)


def get_chunk_slices(length: int, chunk_size: int) -> Iterator[slice]:
    for start in range(0, length, chunk_size):
        end = min(start + chunk_size, length)
        yield slice(start, end)


def load_probabilities(folder: Path):
    with h5py.File(folder / "data.hdf5", "r") as f:
        x_len, y_len = f["probabilities"].shape[:2]
        for x_slice in get_chunk_slices(x_len, CHUNK_SIZE):
            for y_slice in get_chunk_slices(y_len, CHUNK_SIZE):
                yield (x_slice, y_slice), f["probabilities"][x_slice, y_slice]


def colorcode_probabilities(probabilities: np.ndarray) -> np.ndarray:
    predicted_classes = np.argmax(probabilities, axis=2).astype(np.uint8)
    max_prob = np.take_along_axis(
        probabilities, predicted_classes[..., None], axis=2
    ).squeeze()
    del probabilities
    max_prob = max_prob.astype(np.float32)
    colored_probabilities = CLASS_COLORS[predicted_classes]
    colored_probabilities[:, :, 0] = colored_probabilities[:, :, 0] * max_prob
    colored_probabilities[:, :, 1] = colored_probabilities[:, :, 1] * max_prob
    colored_probabilities[:, :, 2] = colored_probabilities[:, :, 2] * max_prob
    return colored_probabilities


def load_and_colorcode_probabilities(folder: Path) -> np.ndarray:
    """Pre-allocates the full output once, then fills it chunk by chunk:
    peak memory is one output array plus one chunk, never the whole map."""
    with h5py.File(folder / "data.hdf5", "r") as f:
        x_len, y_len = f["probabilities"].shape[:2]
    colored_probabilities = np.zeros((x_len, y_len, 3), dtype=np.uint8)
    for chunk_slice, chunk in load_probabilities(folder):
        colored_probabilities[chunk_slice] = colorcode_probabilities(chunk)
    return colored_probabilities


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
