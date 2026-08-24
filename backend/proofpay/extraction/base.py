from abc import ABC, abstractmethod

from proofpay.core.models import PaymentClaim


class ReceiptExtractor(ABC):
    """Abstract base class for all receipt OCR extractors."""

    @abstractmethod
    def extract(self, image_bytes: bytes, claim_id: str, **kwargs) -> PaymentClaim:
        """
        Extract payment structured data from a receipt image.
        
        Args:
            image_bytes: The raw image bytes.
            claim_id: UUID string for the generated PaymentClaim object.
            
        Returns:
            PaymentClaim: Structured parsed fields. Unreadable fields MUST
                          be set to None. Do not hallucinate values.
        """
        pass
