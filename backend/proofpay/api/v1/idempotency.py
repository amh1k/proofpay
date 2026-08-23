"""In-memory idempotency contract used by the OpenAPI stub.

The persistence phase will replace this registry with the database-backed
`idempotency_records` table. Keeping the fingerprint behavior here lets the
frontend integrate with the final request semantics now.
"""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, status

from .schemas import VerificationResult

_responses: dict[tuple[str, str], tuple[str, VerificationResult]] = {}


def request_fingerprint(order_id: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return hashlib.sha256(f"{order_id}:{digest}".encode()).hexdigest()


def find_existing(merchant_id: str, key: str, fingerprint: str) -> VerificationResult | None:
    record = _responses.get((merchant_id, key))
    if record is None:
        return None
    stored_fingerprint, response = record
    if stored_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_CONFLICT: the key was used with a different request",
        )
    return response


def store_response(
    merchant_id: str, key: str, fingerprint: str, response: VerificationResult
) -> None:
    _responses[(merchant_id, key)] = (fingerprint, response)


def reset() -> None:
    _responses.clear()
