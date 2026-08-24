"""Error hierarchy for the extraction layer.

These are the ONLY exceptions that may cross the `extraction/` boundary.
Vendor exceptions (dashscope errors, httpx timeouts) are caught inside
adapters and re-raised as one of these five.
"""

__all__ = [
    "ExtractionError",
    "ExtractionMalformed",
    "ExtractionRefused",
    "ExtractionTimeout",
    "ExtractionUnavailable",
]


class ExtractionError(Exception):
    """Base for all extraction-layer failures."""


class ExtractionTimeout(ExtractionError):
    """The model call exceeded our wall-clock budget (hard cap: 12s)."""


class ExtractionUnavailable(ExtractionError):
    """429/403/quota/5xx/network — the service is reachable but won't serve us."""


class ExtractionMalformed(ExtractionError):
    """The model returned something we could not parse after one repair round."""


class ExtractionRefused(ExtractionError):
    """Content filter / DataInspectionFailed — do NOT retry."""
