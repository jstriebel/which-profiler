# Step A: pure-Python CSV read + colorcode (no numpy, stdlib only).

# The naive starting point before step B reaches for numpy at all: nested
# Python loops both for parsing the ``np.savetxt``-formatted CSVs and for the
# colorcode compute, with tiny per-field/per-channel helper functions — the
# innocent "clean code" style that multiplies the call count and makes
# instrumenting profilers like cProfile visibly expensive. cProfile / py-spy
# show the hotspot living in Python bytecode itself, not in some C extension
# call. Zero third-party imports also makes this the one script in the arc
# that runs unmodified on CPython 3.15 today; numpy/h5py/scikit-image/
# scikit-learn have no 3.15 wheels yet.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

CLASS_COLORS: list[list[int]] = [[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]]


def _parse_field(value: str) -> float:
    """One call per CSV field."""
    return float(value)


def _read_csv(path: Path) -> list[list[float]]:
    """Parse an ``np.savetxt``-style whitespace-separated CSV, stdlib only."""
    with path.open() as f:
        return [[_parse_field(v) for v in line.split()] for line in f]


def load_probabilities(folder: Path) -> list[list[list[float]]]:
    """Read the four per-class CSVs and zip them into per-pixel probability tuples."""
    per_class = [_read_csv(folder / f"{c}.csv") for c in range(4)]
    rows, cols = len(per_class[0]), len(per_class[0][0])
    return [
        [[per_class[c][row][col] for c in range(4)] for col in range(cols)]
        for row in range(rows)
    ]


def _argmax(values: list[float]) -> int:
    """One call per pixel."""
    index = 0
    for i, value in enumerate(values):
        if value > values[index]:
            index = i
    return index


def _scale_channel(channel: int, factor: float) -> float:
    """One call per pixel per color channel."""
    return channel * factor


def colorcode_probabilities(
    probabilities: list[list[list[float]]],
) -> list[list[list[float]]]:
    colored_probabilities = []
    for probabilities_row in probabilities:
        colored_probabilities_row = []
        for class_probabilities in probabilities_row:
            class_index = _argmax(class_probabilities)
            max_prob = class_probabilities[class_index]
            colored_probability = [
                _scale_channel(c, max_prob) for c in CLASS_COLORS[class_index]
            ]
            colored_probabilities_row.append(colored_probability)
        colored_probabilities.append(colored_probabilities_row)
    return colored_probabilities


def load_and_colorcode_probabilities(folder: Path) -> list[list[list[float]]]:
    probabilities = load_probabilities(folder)
    return colorcode_probabilities(probabilities)


def run(data: Path) -> list[list[list[float]]]:
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
