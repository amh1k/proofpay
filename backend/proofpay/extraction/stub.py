import hashlib
import json
from datetime import datetime
from pathlib import Path

from proofpay.core.models import PaymentClaim
from proofpay.core.money import Money
from proofpay.core.timex import ClaimedInstant, GRANULARITY_MINUTE, GRANULARITY_DAY
from proofpay.extraction.base import ReceiptExtractor


class OfflineStubExtractor(ReceiptExtractor):
    """
    Deterministic offline stub extractor.
    Hashes the image bytes and looks up the extraction ground truth perfectly 
    from the demo manifest. Needs no API key. Falls back to None if not found 
    (though for the demo it should always perfectly hit).
    """
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        with open(manifest_path, 'r', encoding='utf-8') as f:
            self.manifest = json.load(f)

    def extract(self, image_bytes: bytes, claim_id: str, **kwargs) -> PaymentClaim:
        sha256 = hashlib.sha256(image_bytes).hexdigest()

        # Find matching image
        matching_case = None
        for case in self.manifest.get('cases', []):
            img_meta = case.get('images', {})
            if img_meta.get('sha256') == sha256:
                matching_case = case
                break

        if not matching_case:
            raise ValueError(
                f"Image hash {sha256} not found in manifest! "
                "The StubExtractor only works with committed demo fixtures."
            )

        vis = matching_case['visible']

        # Parse timestamp safely
        occ_at = None
        raw_ts = vis.get('raw_timestamp_text')
        if raw_ts:
            try:
                dt = datetime.strptime(raw_ts, "%d %b %Y, %I:%M %p")
                occ_at = ClaimedInstant.from_local(dt, granularity_s=GRANULARITY_MINUTE)
            except ValueError:
                dt = datetime.strptime(raw_ts, "%d %b %Y")
                occ_at = ClaimedInstant.from_local(dt, granularity_s=GRANULARITY_DAY)

        amt = None
        if vis.get('amount_paisa'):
            amt = Money(vis.get('amount_paisa'))

        return PaymentClaim(
            claim_id=claim_id,
            provider=vis.get('rail'),
            amount=amt,
            sender_name=vis.get('sender_name'),
            receiver_name=vis.get('receiver_name'),
            reference_id=vis.get('reference_id'),
            occurred_at=occ_at,
            parser_version="offline_stub_v1"
        )
