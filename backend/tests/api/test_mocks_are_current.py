"""The committed frontend mocks must still be what the engine produces.

`scripts/generate_api_mocks.py` runs the REAL pipeline over the REAL receipts
and writes three files into the frontend tree. Nothing until now re-ran it. That
is a gap with a specific shape, and it is worth naming precisely, because it is
not the usual "a generated file went out of date" annoyance:

    DecisionPolicy.fingerprint() is a sha256 over asdict(policy), so ADDING a
    field moves it even when no existing threshold is touched. The mocks carry
    that fingerprint. So the mocks go stale on policy changes that alter no
    verdict and break no other test -- silently, five files downstream, in the
    one artifact a demo in mock mode actually renders.

    D:  frontend runs VITE_USE_MOCKS=true by default (api/client.ts), so the
        screen a room sees can be a recording of an engine that no longer
        exists, stamped with the provenance of an engine that never did.

The generator already refuses to write a mock whose STATUS disagrees with its
own table -- `build()` raises SystemExit. It does not defend confidence,
evidence scores, reason lists, summary text, fired_rule_id or the three
provenance stamps, all of which it will happily rewrite. Those are what this
file watches.

WHY IT COMPARES RENDERED TEXT AND NOT PARSED DICTS:
    `write()` pins `newline="\\n"` on purpose -- the frontend tree is LF
    throughout and a CRLF rewrite buries a one-line regeneration inside a
    whole-file diff. A dict comparison cannot see that. Comparing the bytes
    catches a drifted verdict and a drifted line ending with one assertion.

WHEN THIS GOES RED, IT IS NOT ASKING TO BE EDITED. Run:

    cd backend && uv run python ../scripts/generate_api_mocks.py

and commit the three files it writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

import pytest

from proofpay.core.decide import ENGINE_VERSION, RULESET_VERSION, DecisionPolicy

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MOCKS: Final[Path] = REPO_ROOT / "frontend" / "src" / "mocks"

# scripts/ sits at the repo root rather than inside the backend package, the
# same arrangement tools/ has -- see tests/test_pk_data.py, which reaches for
# tools/ this way. Importing the generator rather than re-implementing it is
# the whole point: a second copy of the payload shape here would be one more
# thing to keep in step, which is the drift the generator exists to remove.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_api_mocks as gen

REGENERATE: Final[str] = (
    "Re-run it from the backend directory:\n"
    "    cd backend && uv run python ../scripts/generate_api_mocks.py\n"
    "Do not hand-edit the JSON -- it is generated, and an edit here is a "
    "verdict the live API does not produce."
)


@pytest.fixture(scope="module")
def results() -> list[dict]:
    """The five demo receipts, decided for real, exactly as the generator does."""
    return [gen.build(receipt) for receipt in gen.DEMO_RECEIPTS]


def _committed(name: str) -> str:
    """The mock as it sits on disk, newlines untranslated.

    `read_text` with the default newline handling turns CRLF into LF on the way
    in, which would hide the very rewrite the explicit `newline="\\n"` in
    `write()` exists to prevent.
    """
    return (MOCKS / name).read_bytes().decode("utf-8")


def test_verifications_mock_matches_a_fresh_engine_run(results: list[dict]) -> None:
    """Every field of every mocked verification, not just its verdict."""
    fresh = gen.rendered(gen.verifications_payload(results))
    assert _committed("verifications.json") == fresh, (
        f"frontend/src/mocks/verifications.json is stale. {REGENERATE}"
    )


def test_orders_mock_matches_the_picker_the_api_serves() -> None:
    """The picker rows are projected from `engine_demo`; the mock must be that
    projection and not a snapshot of an older one."""
    assert _committed("orders.json") == gen.rendered(gen.orders_payload()), (
        f"frontend/src/mocks/orders.json is stale. {REGENERATE}"
    )


def test_dashboard_mock_counts_the_verdicts_that_are_actually_produced(
    results: list[dict],
) -> None:
    assert _committed("dashboard.json") == gen.rendered(gen.dashboard_payload(results)), (
        f"frontend/src/mocks/dashboard.json is stale. {REGENERATE}"
    )


def test_every_mocked_verification_carries_the_live_engine_provenance() -> None:
    """The narrow failure this whole file was written for, asserted narrowly.

    A policy change that adds a field moves `policy_fingerprint` and nothing
    else. If the three tests above are ever loosened, this one still names the
    stamps by hand, and its failure message says which of the three moved --
    which the byte comparison cannot, because a 22 KB diff reports only that
    two long strings differ.
    """
    expected = {
        "ruleset_version": RULESET_VERSION,
        "policy_fingerprint": DecisionPolicy().fingerprint(),
        "engine_version": ENGINE_VERSION,
    }

    items = json.loads(_committed("verifications.json"))["items"]
    assert items, "no mocked verifications to check"

    for item in items:
        for field, live in expected.items():
            assert item[field] == live, (
                f"{item['id']} was recorded under {field}={item[field]!r}, but the "
                f"engine now stamps {live!r}. {REGENERATE}"
            )


def test_the_stub_history_agrees_with_the_live_engine_on_provenance() -> None:
    """A history row and a fresh check must not contradict each other on screen.

    `stub_data`'s five history rows are hand-written illustration -- their
    amounts and names are invented and that is fine. Their provenance is not
    invented: it is derived from the same engine constants, so a merchant
    comparing yesterday's row against today's check sees one ruleset and one
    fingerprint rather than two. This test is what keeps that derivation from
    being quietly replaced by a literal again.
    """
    from proofpay.api.v1.stub_data import DEMO_VERIFICATIONS

    for record in DEMO_VERIFICATIONS:
        assert record.ruleset_version == RULESET_VERSION
        assert record.policy_fingerprint == DecisionPolicy().fingerprint()
        assert record.engine_version == ENGINE_VERSION
