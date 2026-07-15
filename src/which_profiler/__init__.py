"""which-profiler: which profiler, when?

Which Python profiler fits your workload? Filter by focus, attach mode, and
more; get a runnable command.
"""

from __future__ import annotations

from .cli import app, main

__all__ = ["app", "main"]
