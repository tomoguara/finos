"""Small statistics shared by evaluation and the cost report.

Pure Python with no third-party imports, so the light ``finos cost`` command
can use it without loading the evaluation runner.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["mean", "percentile"]


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile; ``None`` for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(round(fraction * len(ordered), 9))
    return ordered[min(len(ordered), max(rank, 1)) - 1]


def mean(values: Sequence[float]) -> float | None:
    """The arithmetic mean; ``None`` for no values."""
    return sum(values) / len(values) if values else None
