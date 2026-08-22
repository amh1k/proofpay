"""Decay curves for numeric tolerance.

A boolean window ("within 15 minutes") is the wrong shape for physical
tolerance: it treats 14m59s as perfect and 15m01s as worthless, and it hides
the one number a reviewer wants to argue about. A decay curve replaces the
window with two numbers that can be defended in a design review:

* ``offset`` — a free zone of full similarity, where the difference is explained
  by known noise (device clock skew, initiation-vs-settlement lag).
* ``scale`` — the half-similarity distance *past* the offset. At
  ``offset + scale`` similarity is exactly 0.5, by construction.

The formula is Elasticsearch's / recordlinkage's Gaussian decay, taken from the
recordlinkage numeric comparison source rather than reimplemented by feel::

    d' = max(0, |a - b| - offset)
    sim = 2 ** (-(d' / scale) ** 2)

`recordlinkage` itself is deliberately not a dependency: it drags pandas and
numpy into a layer that must stay pure. The formula is nine lines; the library
is not worth the import.
"""

from __future__ import annotations

__all__ = ["exponential", "gauss"]


def _prepare(distance: float, offset: float, scale: float) -> float:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if scale <= 0:
        raise ValueError("scale must be > 0")
    return max(0.0, abs(distance) - offset)


def gauss(distance: float, offset: float, scale: float) -> float:
    """Gaussian decay: flat top, hard tail. The default for timestamps.

    The flat top matches the physical reality of clock skew — a few seconds of
    disagreement is *not* weaker evidence — while the squared tail punishes a
    far miss hard, which is what stops "same hour" from looking like a match.
    """
    d = _prepare(distance, offset, scale)
    return 2.0 ** (-((d / scale) ** 2))


def exponential(distance: float, offset: float, scale: float) -> float:
    """Exponential decay: same offset/scale contract, heavier tail.

    Use where a far miss should still carry a little evidence rather than being
    treated as noise. Both curves agree at ``distance == offset`` (1.0) and at
    ``distance == offset + scale`` (0.5); they differ only in between and beyond.
    """
    d = _prepare(distance, offset, scale)
    return 2.0 ** (-(d / scale))
