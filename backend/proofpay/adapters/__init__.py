"""Adapters: the layer that talks to the outside world so `core` never has to.

`proofpay.core` is pure — no clock, no filesystem, no network, no image
toolkit, no database. Everything it needs from the world it is *given*, as
plain frozen dataclasses, by whoever calls it. This package is where the giving
happens: reading a store, hashing bytes, calling a vendor SDK.

Each adapter is expected to carry a local fallback so the demo runs with no
cloud account attached (see docs/phases/phase2-api.md). Today:

* `proof_store` — which proof images a merchant has already had accepted.
  In-memory until `payment_proofs` is wired up.

The vision and OCR adapters landed under `proofpay/extraction/` instead, and
`tests/test_architecture.py` pins that: no module outside `proofpay/extraction/`
may import `dashscope` or `openai`, this package included.
"""
