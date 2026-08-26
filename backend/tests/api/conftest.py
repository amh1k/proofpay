"""Shared setup for the API tests.

The verification endpoint keeps two pieces of cross-request memory that live in
module-level dicts rather than in the app object: the idempotency registry and
the accepted-proof store. `create_app()` therefore does NOT give a test a clean
slate, and a test that submits a receipt leaves that receipt visible to every
test that runs after it.

For idempotency that has always been survivable, because each test picks its own
key. For proof reuse it is not: the whole signal is "these bytes have been seen
before", so one test's VERIFIED submission is exactly the state that would make
the next test's identical submission a DUPLICATE. Left alone it would make the
suite order-dependent -- the worst kind of flake, because it passes locally and
fails on whichever machine happens to shard differently.
"""

from __future__ import annotations

import pytest

from proofpay.adapters.proof_store import reset as reset_proof_store
from proofpay.api.v1.idempotency import reset as reset_idempotency


@pytest.fixture(autouse=True)
def _clean_request_memory() -> None:
    """Every API test starts with no remembered requests and no proof history."""
    reset_idempotency()
    reset_proof_store()
