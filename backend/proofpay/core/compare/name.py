"""The sender-name comparison: a score-ordered ladder of named levels.

Names are the noisiest field on a Pakistani wallet receipt and the one a human
reviewer trusts most, so the whole point of this module is to turn "how similar
are these two strings" into a *labelled category a merchant can read*:
`NAME_MASK_OK` -> "Consistent with masked name" is an explanation; 0.8413 is not.

Four domain facts drive every decision here:

1. **Transliteration.** `Muhammad`, `Mohammad`, `Mohd` and `Md` are one name.
   `proofpay.core.normalize.normalize_name` folds those families before we ever
   score, so scoring only ever sees canonical tokens.
2. **Masking.** Wallet receipts routinely print `MUHAMMAD A***`. A ladder with
   no level for "the visible part is consistent with the mask" scores a
   perfectly good payment as a mismatch. Masks are first class here.
3. **Initials.** `M. Ali` and `Muhammad Ali` are the same customer, and a
   whole-string scorer cannot see that. Per-token alignment can.
4. **Common given names.** An enormous share of Pakistani male names contain
   `Muhammad`. Two records agreeing on it is nearly zero evidence, while two
   records agreeing on `Zulqarnain` is very strong evidence. Term-frequency
   (IDF) weighting is therefore not a refinement, it is load bearing: without it
   the engine confidently matches the wrong transaction.

Scoring never uses a whole-string scorer - see `_tok_sim` for the per-scorer
justification.

This module owns no numbers. Every cut-point arrives as a `NameThresholds`,
which `DecisionPolicy.name_thresholds()` builds from the `name_*` fields of the
policy; the IDF floor arrives as `build_name_idf(..., floor=...)`. Restating the
values here would create a second place to read them from and a first place to
get them wrong, so `policy.py` is the only place they appear.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rapidfuzz.distance import JaroWinkler

from proofpay.core.compare.levels import (
    Agreement,
    Comparison,
    FieldOutcome,
    Level,
    else_level,
)
from proofpay.core.normalize import (
    ACCOUNT_NOISE,
    COMMON_NAME_TOKENS,
    HONORIFICS,
    fold_token,
    normalize_name,
)
from proofpay.core.reasons import ObservationCode

__all__ = [
    "COMMON_NAME_TOKENS",
    "INITIAL_MATCH_SIM",
    "SENDER_NAME",
    "MaskToken",
    "NameThresholds",
    "build_name_idf",
    "compare_name",
    "mask_consistency",
    "mask_tokens",
    "name_comparison",
    "name_metrics",
    "name_observations",
    "seed_idf",
    "token_alignment",
]


# ---------------------------------------------------------------------------
# Thresholds (supplied by policy, never defaulted here)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class NameThresholds:
    """The four cut-points of the name ladder.

    No defaults, deliberately: a default here would be a threshold living
    outside `policy.py`, and the first thing that happens to a defaulted
    threshold is that nobody ever tunes it. Same convention as
    `timex.hour_offset_artifact(..., tol_s)`.
    """

    strong: float       # token_score at/above which a match is "minor spelling"
    initials: float     # token_score at/above which an expanded initial counts
    pair_min: float     # per-token similarity below which two tokens are unrelated
    common_idf: float   # IDF-weighted score below which the evidence is worthless

    def __post_init__(self) -> None:
        for name in ("strong", "initials", "pair_min", "common_idf"):
            value = getattr(self, name)
            if not isinstance(value, float) or not (0.0 <= value <= 1.0):
                raise ValueError(f"NameThresholds.{name} must be a float in 0.0..1.0")
        if not (self.strong >= self.initials >= self.pair_min):
            raise ValueError(
                "NameThresholds: expected strong >= initials >= pair_min, got "
                f"{self.strong} / {self.initials} / {self.pair_min}"
            )


# ---------------------------------------------------------------------------
# Term frequency: what a matching token is actually worth
# ---------------------------------------------------------------------------



def seed_idf(floor: float) -> dict[str, float]:
    """Cold-start IDF: the static common-name list, all at the floor.

    Everything absent from the map is worth 1.0 at lookup time (see
    `token_alignment`), so a cold merchant still gets full credit for a
    distinctive surname while getting almost none for `Muhammad`.
    """
    return {token: floor for token in COMMON_NAME_TOKENS}


def build_name_idf(
    all_names: Iterable[Sequence[str]],
    *,
    floor: float,
) -> dict[str, float]:
    """IDF over a merchant's own name feed, floored and capped.

    `floor` keeps a common token from being treated as evidence; the 1.0 cap
    keeps a token seen once from dominating the weighted score. Splink's
    `tf_minimum_u_value` exists for the same reason, in the same place.
    """
    docs = [tuple(toks) for toks in all_names]
    n = len(docs)
    if n < 2:
        # log(1) == 0: no discrimination information exists yet, and inventing
        # some would be worse than falling back to the static list.
        return seed_idf(floor)
    df = Counter(token for toks in docs for token in set(toks))
    denom = math.log(n)
    idf = {
        token: max(floor, min(1.0, math.log(n / (1 + count)) / denom))
        for token, count in df.items()
    }
    idf.update(seed_idf(floor))
    return idf


# ---------------------------------------------------------------------------
# Per-token similarity and alignment
# ---------------------------------------------------------------------------

#: The similarity *value* assigned to "initial agrees with full token"
#: ("m" vs "muhammad"). Not a threshold - nothing is ever compared against it;
#: it is the evidence an initial carries, and it sits just under a real
#: spelling match so that an initials match can never outrank a full one.
INITIAL_MATCH_SIM = 0.90


def _tok_sim(a: str, b: str) -> float:
    """Similarity of two *already normalised* name tokens.

    Jaro-Winkler, and only Jaro-Winkler, because of what the alternatives do to
    this data:

    * `fuzz.ratio` - fine for single tokens, destroyed by word order on names.
    * `fuzz.token_sort_ratio` - solves word order, but breaks when one side has
      an extra token, which is the normal case here (`Muhammad Ali Khan` vs
      `Ali Khan`).
    * `fuzz.token_set_ratio` - returns 100 for any subset, so `Muhammad` alone
      scores a perfect match against `Muhammad Ali Khan`. In a payment engine
      that is a wrong-transaction match, not a lenient one.
    * `fuzz.partial_ratio` - far too generous on short tokens.
    * `fuzz.WRatio` - an unexplainable heuristic blend; a merchant asking "why
      did you match this?" deserves an answer.

    Jaro-Winkler is the right *per-token* scorer: it handles transposition
    (`Zulqarnain`/`Zulqarnian` = 0.98) and rewards prefix agreement, which is
    exactly how transliteration errors behave. Whole-string comparison is
    handled by aligning tokens, not by a whole-string scorer.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) == 1 or len(b) == 1:
        # JW on a single character is noise; an initial is a structural fact,
        # not a spelling, so it gets a fixed value.
        return INITIAL_MATCH_SIM if a[0] == b[0] else 0.0
    return JaroWinkler.normalized_similarity(a, b)


def token_alignment(
    claim: Sequence[str],
    truth: Sequence[str],
    idf: Mapping[str, float],
    *,
    pair_min: float,
) -> dict[str, Any]:
    """Greedy best-match token alignment, plain and IDF-weighted.

    **Pairs are taken in order of similarity, not in order of token.** Visiting
    claim tokens lexically - the obvious implementation, and the one this
    function used first - lets a weak pairing consume the truth token that a
    strong one needed, because a single-letter initial sorts before the full
    token sharing its first letter. `A. Ali Khan` against `Ali Khan` had `a`
    take `ali` at 0.90, leaving the real `ali` unmatched and scoring 0.633
    where the correct alignment scores 0.667; `M Muhammad` against
    `Muhammad Mahmood` scored 0.82 one way round and 0.95 the other. Initials
    are exactly the case section 3 of the design guide calls load-bearing, so
    under-scoring them is not a rounding difference.

    Sorting candidate pairs by descending similarity fixes both at once: the
    alignment can only improve, and it becomes **symmetric** - which side is
    the claim no longer changes `token_score`.

    Deterministic by construction: candidates are ordered by similarity, then
    by the unordered token pair, then by position, so the same two names always
    produce the same pairs and a stored decision stays replayable. The final
    `pairs` tuple is re-sorted by claim token because it is read by humans in
    the evidence drawer.

    Deviation from the design guide, deliberate: a pairing requires
    `sim >= pair_min` rather than `sim > 0`. Jaro-Winkler puts `ali`/`zulqarnain`
    at 0.46; accepting that as a pairing both inflates `token_score` and - much
    worse - consumes the truth token that the *real* claim token needed.

    Two scores come out, and they answer different questions:

    * `token_score` - how much of the name matched, treating every token as
      equally informative.
    * `idf_weighted_score` - how much *evidence* matched. Each token can
      contribute at most its IDF, and the denominator counts every token as if
      it were fully distinctive, so agreeing on `Muhammad Ali` lands near the
      floor while agreeing on `Zulqarnain Haider` lands near 1.0. This absolute
      form is the point: normalising by the matched tokens' own IDF (as the
      guide's snippet does) returns ~1.0 for two identical common names and so
      cannot detect the very problem it exists to detect.
    """
    # Every possible pairing, best first. `min`/`max` of the two tokens is the
    # tie-break rather than the claim token alone, so the ordering does not
    # depend on which side is the claim; the indices break the remaining ties
    # between repeated tokens, which are interchangeable by definition.
    ranked = sorted(
        (
            (_tok_sim(c, t), min(c, t), max(c, t), i, j, c, t)
            for i, c in enumerate(claim)
            for j, t in enumerate(truth)
        ),
        key=lambda p: (-p[0], p[1], p[2], p[3], p[4]),
    )

    claim_taken: set[int] = set()
    truth_taken: set[int] = set()
    pairs: list[tuple[str, str, float]] = []
    used_initial = False
    for sim, _lo, _hi, i, j, token, other in ranked:
        if sim < pair_min:
            break  # sorted descending: nothing after this can qualify either
        if i in claim_taken or j in truth_taken:
            continue
        claim_taken.add(i)
        truth_taken.add(j)
        if len(token) == 1 or len(other) == 1:
            used_initial = True
        pairs.append((token, other, sim))

    pairs.sort(key=lambda p: (p[0], p[1]))
    remaining = [t for j, t in enumerate(truth) if j not in truth_taken]

    denom = max(len(claim), len(truth))
    if not pairs or denom == 0:
        return {
            "token_score": 0.0,
            "idf_weighted_score": 0.0,
            "matched_idf_mass": 0.0,
            "initials_compatible": False,
            "pairs": (),
            "unmatched_truth": tuple(sorted(remaining)),
        }
    mass = sum(sim * min(1.0, idf.get(token, 1.0)) for token, _, sim in pairs)
    return {
        "token_score": sum(sim for _, _, sim in pairs) / denom,
        "idf_weighted_score": mass / denom,
        "matched_idf_mass": mass,
        "initials_compatible": used_initial,
        "pairs": tuple(pairs),
        "unmatched_truth": tuple(sorted(remaining)),
    }


# ---------------------------------------------------------------------------
# Masked names
# ---------------------------------------------------------------------------

# A mask run: asterisks, hashes, bullets, or a run of two or more `x`. A single
# `x` is a letter (`Xavier`); two in a row inside a name field is a wallet
# hiding something. `normalize_name` deletes these characters entirely, which is
# right for scoring and useless for mask checking, so masks are parsed here from
# the raw text.
_MASK_RUN = re.compile(r"[*#•·∙]+|x{2,}")
_TOKEN_SPLIT = re.compile(r"[\s.\-_,]+")
_NOT_LETTER = re.compile(r"[^a-z]+")


@dataclass(frozen=True, slots=True)
class MaskToken:
    """One receipt token with its mask structure kept intact.

    `raw` is the visible letters as printed (`moh` of `MOH****`); `text` is that
    prefix after transliteration folding. Both are kept because a prefix must be
    testable against both forms of the other side: `moh` is a prefix of
    `mohammad` but not of its canonical fold `muhammad`.
    """

    text: str
    raw: str
    masked: bool
    hidden: int = 0

    @property
    def is_wildcard(self) -> bool:
        """Fully hidden (`****`): consistent with anything, evidence for nothing."""
        return self.masked and not self.raw


def _ascii_fold(raw: str) -> str:
    """Casefold and strip diacritics while *keeping* mask characters.

    `normalize_name` reaches ASCII via `encode("ascii", "ignore")`, which would
    delete a bullet mask along with the diacritics.
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def mask_tokens(raw: str | None) -> tuple[MaskToken, ...]:
    """Tokenise a name while preserving which tokens are masked, and how."""
    if not raw:
        return ()
    out: list[MaskToken] = []
    for chunk in _TOKEN_SPLIT.split(_ascii_fold(raw)):
        if not chunk:
            continue
        hit = _MASK_RUN.search(chunk)
        if hit is None:
            text = _NOT_LETTER.sub("", chunk)
            folded = fold_token(text)
            if not folded or folded in HONORIFICS or folded in ACCOUNT_NOISE:
                continue
            out.append(MaskToken(text=folded, raw=text, masked=False))
            continue
        visible = _NOT_LETTER.sub("", chunk[: hit.start()])
        hidden = sum(len(m.group(0)) for m in _MASK_RUN.finditer(chunk))
        out.append(
            MaskToken(text=fold_token(visible), raw=visible, masked=True, hidden=hidden)
        )
    return tuple(out)


def _mask_pair_ok(a: MaskToken, b: MaskToken, *, strong: float) -> tuple[bool, bool]:
    """`(consistent, carries_evidence)` for one aligned token pair."""
    if not a.masked and not b.masked:
        sim = _tok_sim(a.text, b.text)
        return (sim >= strong, sim >= strong)
    if a.is_wildcard or b.is_wildcard:
        return (True, False)
    if a.masked and b.masked:
        # Both sides masked: the shorter visible prefix must prefix the longer.
        short, long_ = sorted((a.raw, b.raw), key=len)
        return (long_.startswith(short), long_.startswith(short))
    hidden, shown = (a, b) if a.masked else (b, a)
    ok = shown.raw.startswith(hidden.raw) or shown.text.startswith(hidden.text)
    return (ok, ok)


def mask_consistency(
    claim: Sequence[MaskToken],
    truth: Sequence[MaskToken],
    *,
    strong: float,
) -> dict[str, Any]:
    """Is a masked rendering of a name consistent with the ledger's name?

    Positional alignment, not greedy: a mask hides the tail of a token, and a
    receipt prints the tokens in order, so `MUHAMMAD A***` aligns to
    `Muhammad Ali` position by position. The longer side may carry extra
    trailing tokens - receipts truncate.

    Consistency is not a match: every aligned pair must be compatible *and* at
    least one pair must carry actual evidence, so `**** ****` against any name
    is not "consistent", it is unknown.
    """
    mask_present = any(t.masked for t in claim) or any(t.masked for t in truth)
    aligned = min(len(claim), len(truth))
    result: dict[str, Any] = {
        "mask_present": mask_present,
        "mask_consistent": False,
        "mask_hidden_chars": sum(t.hidden for t in claim) + sum(t.hidden for t in truth),
        "mask_pairs": (),
    }
    if not mask_present or aligned == 0:
        return result

    pairs: list[tuple[str, str, bool]] = []
    consistent = True
    evidenced = False
    for left, right in zip(claim[:aligned], truth[:aligned]):
        ok, evidence = _mask_pair_ok(left, right, strong=strong)
        pairs.append((_render(left), _render(right), ok))
        consistent = consistent and ok
        evidenced = evidenced or evidence
    result["mask_pairs"] = tuple(pairs)
    result["mask_consistent"] = consistent and evidenced
    return result


def _render(token: MaskToken) -> str:
    """Display form of a mask token, for the evidence drawer."""
    return f"{token.raw}***" if token.masked else token.raw


# ---------------------------------------------------------------------------
# The metric bundle the level predicates read
# ---------------------------------------------------------------------------

def name_metrics(
    claim_raw: str | None,
    truth_raw: str | None,
    *,
    idf: Mapping[str, float],
    thresholds: NameThresholds,
) -> dict[str, Any]:
    """Everything the ladder needs, computed once.

    The bundle becomes `FieldOutcome.detail` verbatim, so the thresholds that
    were applied are recorded alongside the numbers they were applied to. A
    decision replayed a year later can be checked against the policy that
    produced it without guessing.
    """
    claim_tokens = normalize_name(claim_raw) if claim_raw else ()
    truth_tokens = normalize_name(truth_raw) if truth_raw else ()
    both_present = bool(claim_tokens) and bool(truth_tokens)

    ctx: dict[str, Any] = {
        "claim_tokens": claim_tokens,
        "truth_tokens": truth_tokens,
        "both_present": both_present,
        "t_strong": thresholds.strong,
        "t_initials": thresholds.initials,
        "t_pair_min": thresholds.pair_min,
        "t_common_idf": thresholds.common_idf,
    }
    ctx.update(
        token_alignment(claim_tokens, truth_tokens, idf, pair_min=thresholds.pair_min)
    )
    ctx.update(
        mask_consistency(
            mask_tokens(claim_raw), mask_tokens(truth_raw), strong=thresholds.strong
        )
    )
    if not both_present:
        # A mask on one side of a name we could not read at all is not evidence.
        ctx["mask_consistent"] = False
    ctx["pair_count"] = len(ctx["pairs"])
    return ctx


def name_observations(ctx: Mapping[str, Any]) -> tuple[str, ...]:
    """Neutral notes for the decision's `observations` - never a verdict."""
    notes: list[str] = []
    if ctx.get("mask_present"):
        notes.append(ObservationCode.NAME_MASKED)
    if ctx.get("pair_count") and ctx["idf_weighted_score"] < ctx["t_common_idf"]:
        notes.append(ObservationCode.NAME_COMMON_TOKENS_ONLY)
    return tuple(notes)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------
#
# ORDERING, the problem the guide flags in section 2.2 and leaves to us.
#
# `Comparison.__post_init__` demands non-increasing scores, so the ladder is
# written strictly in score order and *every structural preference is expressed
# as a guard on the higher level instead of by reordering*:
#
# * NAME_MISSING scores 0.0, so it cannot sit at the top. It sits second to
#   last, and the only level that could otherwise fire on two unreadable names
#   - NAME_EXACT, since `() == ()` - carries an explicit `both_present` guard.
#   Every other level needs a positive metric that empty names cannot produce.
#   Missing and mismatched both contribute zero evidence; they are told apart by
#   `FieldOutcome.is_missing`, which is what evidence coverage keys off.
#
# * NAME_MASK_OK (0.85) sits *below* NAME_STRONG (0.90) because a mask genuinely
#   carries less information than a full-string match - so NAME_STRONG excludes
#   the masked case explicitly. Without that guard `MUHAMMAD A***` vs
#   `Muhammad Ali` scores token_score 0.95 and would be labelled "minor
#   spelling", which is both a worse explanation and a higher score than the
#   evidence supports.
#
# * NAME_INITIALS (0.80) likewise: an expanded initial is a structural
#   agreement, not a spelling agreement, so NAME_STRONG excludes it and
#   `M. Ali` lands on the row that actually describes it.
#
# * The three pure string-agreement levels - EXACT, STRONG, PARTIAL - are the
#   ones term-frequency weighting must correct, so each requires
#   `idf_weighted_score >= t_common_idf`. Two different customers both called
#   `Muhammad Ali` produce an exact string match on nearly zero evidence; that
#   is the single most likely way this engine matches the wrong transaction, so
#   it falls to NAME_COMMON_ONLY (0.20) instead of NAME_EXACT (1.00).
#   NAME_MASK_OK and NAME_INITIALS are deliberately *not* gated: most of the
#   string is hidden or abbreviated in those cases, so an IDF computed over what
#   remains is not meaningful, and their own scores already discount them.
#
# Every predicate is written to be readable standing alone rather than relying
# on what the levels above it already excluded.

_LEVELS: tuple[Level, ...] = (
    Level(
        "NAME_EXACT",
        "Exact match",
        1.00,
        lambda a, b, c: (
            c["both_present"]
            and a == b
            and c["idf_weighted_score"] >= c["t_common_idf"]
        ),
        Agreement.AGREE,
    ),
    Level(
        "NAME_STRONG",
        "Strong match (minor spelling difference)",
        0.90,
        lambda a, b, c: (
            not c["mask_present"]
            and not c["initials_compatible"]
            and c["token_score"] >= c["t_strong"]
            and c["idf_weighted_score"] >= c["t_common_idf"]
        ),
        Agreement.AGREE,
    ),
    Level(
        "NAME_MASK_OK",
        "Consistent with masked name",
        0.85,
        lambda a, b, c: c["mask_consistent"],
        Agreement.AGREE,
    ),
    Level(
        "NAME_INITIALS",
        "Match with initials expanded",
        0.80,
        lambda a, b, c: (
            c["initials_compatible"] and c["token_score"] >= c["t_initials"]
        ),
        Agreement.AGREE,
    ),
    Level(
        "NAME_PARTIAL",
        "Partial match (shared name component)",
        0.55,
        lambda a, b, c: (
            c["pair_count"] >= 1 and c["idf_weighted_score"] >= c["t_common_idf"]
        ),
        # One distinctive component shared out of several: the names overlap,
        # which is consistent, but a shared surname is not an identification.
        Agreement.WEAK,
    ),
    Level(
        "NAME_COMMON_ONLY",
        "Only a very common name matched",
        0.20,
        lambda a, b, c: (
            c["pair_count"] >= 1 and c["idf_weighted_score"] < c["t_common_idf"]
        ),
        # The names *agree* — on a name so common the agreement identifies
        # nobody. Weak evidence for the match, never evidence against it, and
        # the 0.20 score is what says how little it is worth.
        Agreement.WEAK,
    ),
    Level(
        "NAME_MISSING",
        "Sender name not readable",
        0.00,
        lambda a, b, c: not c["both_present"],
        Agreement.MISSING,
    ),
    # Two readable names with nothing in common. This is the rung that must
    # stop a verification: a claim agreeing on id, amount and time but naming a
    # different sender is exactly the screen a merchant cannot be shown with a
    # green tick on it.
    else_level("NAME_ELSE", "No name match", agreement=Agreement.CONTRADICT),
)


def name_comparison(field: str, *, weight: float = 1.0) -> Comparison:
    """Build the name ladder for a field (`sender_name`, `receiver_name`, ...).

    The level codes are shared across name fields on purpose: `NAME_MASK_OK`
    means the same thing wherever it appears, and `FieldOutcome.field` already
    says which name it was.
    """
    return Comparison(field=field, levels=_LEVELS, weight=weight)


SENDER_NAME = name_comparison("sender_name")


def compare_name(
    claim_raw: str | None,
    truth_raw: str | None,
    *,
    idf: Mapping[str, float],
    thresholds: NameThresholds,
    comparison: Comparison = SENDER_NAME,
) -> FieldOutcome:
    """Normalise, measure, and evaluate the ladder. The engine's entry point."""
    ctx = name_metrics(claim_raw, truth_raw, idf=idf, thresholds=thresholds)
    return comparison.evaluate(ctx["claim_tokens"], ctx["truth_tokens"], ctx)
