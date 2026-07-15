# Step G: long-lived server wrapping the optimized pipeline (step D).

# Idles like a freshly started service, prints ``READY pid=<pid>``, then serves
# "requests" (full load+colorcode calls) for ``--duration`` seconds. The target
# for attach-mode profilers (py-spy, Tachyon, …): PID-attach after READY.

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Standalone scripts, not a package: make the sibling step importable no
# matter where this file is run from.
sys.path.insert(0, str(Path(__file__).parent))

from d_dtypes import load_and_colorcode_probabilities  # noqa: E402

# Idle long enough that an attach-mode profiler is attached before the busy
# loop opens.
IDLE_S = 2.0
DEFAULT_DURATION_S = 10.0


def run(data: Path, duration: float = DEFAULT_DURATION_S) -> int:
    """Idle, announce readiness, then serve the pipeline in a loop for ``duration`` seconds."""
    print(f"READY pid={os.getpid()}", file=sys.stderr)
    sys.stderr.flush()

    time.sleep(IDLE_S)

    requests_served = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < duration:
        result = load_and_colorcode_probabilities(data)
        _ = result
        requests_served += 1
    t1 = time.perf_counter()

    print(f"processed in {t1 - t0:.2f}s", file=sys.stderr)
    print(f"requests served: {requests_served}", file=sys.stderr)
    return requests_served


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
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_S,
        help="serve-loop window, seconds",
    )
    args = parser.parse_args(argv)
    run(args.data, duration=args.duration)


if __name__ == "__main__":
    main()
