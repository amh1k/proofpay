"""ProofPay Receipt Extraction Package.

Public API:
    ExtractionService  — high-level: raw bytes → PaymentClaim
    build_extractor    — factory for choosing DashScope vs offline
    prepare            — image preprocessing
    ReceiptExtractor   — abstract base class
"""

from proofpay.extraction.base import ReceiptExtractor
from proofpay.extraction.errors import (
    ExtractionError,
    ExtractionMalformed,
    ExtractionRefused,
    ExtractionTimeout,
    ExtractionUnavailable,
)
from proofpay.extraction.preprocess import PREPROC_VERSION, PreparedImage, prepare
from proofpay.extraction.schema import (
    ExtractionResult,
    FieldEvidence,
    Maybe,
    RawClaim,
    TamperObservation,
)
from proofpay.extraction.service import ExtractionService, build_extractor

__all__ = [
    "PREPROC_VERSION",
    "ExtractionError",
    "ExtractionMalformed",
    "ExtractionRefused",
    "ExtractionResult",
    "ExtractionService",
    "ExtractionTimeout",
    "ExtractionUnavailable",
    "FieldEvidence",
    "Maybe",
    "PreparedImage",
    "RawClaim",
    "ReceiptExtractor",
    "TamperObservation",
    "build_extractor",
    "prepare",
]
