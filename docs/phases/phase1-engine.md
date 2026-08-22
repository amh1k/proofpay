# Phase 1 — Verification Engine — Best Practices

## 0. What this layer is, and the one rule that defines it

Phase 1 is a **pure library**. It imports `dataclasses`, `decimal`, `datetime`, `zoneinfo`, `rapidfuzz`, `jellyfish` — and nothing from your app. No SQLAlchemy, no FastAPI, no `open()`, no `requests`, no `datetime.now()`.

Everything the engine needs arrives as an argument, including the clock. This is not purity theatre: it is what makes the decision engine *reproducible*, which is the architectural commitment you already made. A decision that reads the wall clock is not reproducible, and a golden-file test of it is a flake generator.

```
proofpay/core/                    # zero I/O, importable in <100ms
  money.py          Money value object (integer minor units)
  timex.py          Instant/ClaimedInstant, tz handling
  models.py         PaymentClaim, LedgerTxn, Order, Allocation  (frozen dataclasses)
  normalize.py      text / name / amount-string / reference-id normalization
  phonetics.py      blocking keys
  compare/
    levels.py       Level, Comparison, evaluate()  ← the splink pattern
    name.py  amount.py  timestamp.py  reference.py  channel.py
  retrieval.py      candidate generation from an in-memory iterable
  duplicates.py     allocation-conflict detection (pure; DB enforces truth)
  decide/
    reasons.py      ReasonCode StrEnum   (stable codes, never reworded)
    policy.py       DecisionPolicy — every threshold, versioned
    rules_v1.py     the ordered rule table
    engine.py       decide(...) -> Decision
  explain.py        Explanation / FieldEvidence render model
```

Enforce the boundary with a test, not a promise:

```python
# tests/test_layering.py
import pathlib, re
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(sqlalchemy|fastapi|httpx|requests|PIL|dashscope)")
def test_core_has_no_io_imports():
    for p in pathlib.Path("proofpay/core").rglob("*.py"):
        bad = [l for l in p.read_text().splitlines() if FORBIDDEN.match(l)]
        assert not bad, f"{p}: {bad}"

def test_core_never_reads_the_clock():
    pat = re.compile(r"(datetime\.now|utcnow|time\.time)\(")
    for p in pathlib.Path("proofpay/core").rglob("*.py"):
        assert not pat.search(p.read_text()), f"{p} reads the clock; pass `now` in"
```

That's 15 lines and it holds the whole phase together. `import-linter` is the "proper" tool; it is not worth the config file this week.

---

## 1. Money and time

### 1.1 Money: integer minor units, `Decimal` only at the parser edge

Float is disqualified, not discouraged. `0.1 + 0.2 != 0.3` in IEEE-754 binary; every equality check in your amount comparison would be silently wrong at the boundary, and boundary behaviour is exactly what you are testing. `Money(1000) == Money(1000)` must be a bit-comparison of two ints.

Both `Decimal` and integer-minor-units are exact. Choose **integer minor units** as the *canonical* representation because:

* It is a single `int`. It hashes, it compares, it serialises to JSON losslessly, it stores as `BIGINT` in Phase 2 with no `numeric(12,2)` round-trip questions, and it survives Hypothesis fuzzing without `InvalidOperation`.
* `Decimal` carries hidden state — context precision, trailing-zero significance (`Decimal("1.50") != Decimal("1.5")` under `compare_total`), and rounding mode. That state is a source of non-reproducibility in an engine that must be reproducible.
* It matches how the payment world actually models money (Stripe, and every ledger you'll ever integrate with).

PKR's ISO 4217 exponent is 2 (paisa), so minor unit = 1 paisa. Pakistani mobile-wallet receipts are effectively always whole rupees, but do **not** hard-code that — normalise to paisa and let the data be boring.

```python
# core/money.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

MINOR_EXPONENT = {"PKR": 2}

@dataclass(frozen=True, slots=True, order=True)
class Money:
    minor: int                 # paisa
    currency: str = "PKR"

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise TypeError("Money.minor must be int (never float/Decimal)")

    @classmethod
    def from_major(cls, major: str | Decimal | int, currency: str = "PKR") -> "Money":
        exp = MINOR_EXPONENT[currency]
        try:
            d = Decimal(str(major))
        except InvalidOperation as e:
            raise ValueError(f"unparseable amount {major!r}") from e
        q = d.quantize(Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP)
        return cls(int(q.scaleb(exp)), currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.minor - other.minor, self.currency)

    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch {self.currency}/{other.currency}")

    @property
    def as_major_str(self) -> str:               # display only
        exp = MINOR_EXPONENT[self.currency]
        return f"{Decimal(self.minor).scaleb(-exp):.{exp}f}"
```

`Decimal` appears exactly once — inside `from_major`, at the parsing boundary. It never leaves.

**Parsing amounts out of OCR text.** This is where the real bugs live. Screenshots yield `"Rs. 1,500"`, `"PKR 1,500.00"`, `"Rs 1500/-"`, `"1٬500"` (Arabic thousands separator U+066C), `"Rs. l,50O"` (OCR letter-for-digit substitution), and `"1.500"` (a European-style thousands separator, or 1.5 rupees — genuinely ambiguous).

```python
# core/normalize.py
import re, unicodedata

_DIGIT_FIXUPS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8"})
_STRIP = re.compile(r"[^\d.,]")

def parse_amount_text(raw: str) -> tuple[Decimal, list[str]]:
    """Returns (value, notes). `notes` are observations for the evidence trail."""
    notes: list[str] = []
    s = unicodedata.normalize("NFKC", raw)          # folds Arabic-Indic digits ٠١٢ -> 012
    s = s.replace("\u066c", ",").replace("\u066b", ".").replace("\u00a0", "")
    if re.search(r"[OolISB]", s):
        s = s.translate(_DIGIT_FIXUPS); notes.append("AMOUNT_OCR_GLYPH_FIXUP")
    s = _STRIP.sub("", s).rstrip(".,")
    # Decide separator role by position, never by locale guessing.
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif "." in s:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):    # 1.500.000 -> thousands
            s = s.replace(".", ""); notes.append("AMOUNT_SEPARATOR_AMBIGUOUS")
    if not s:
        raise ValueError(f"no digits in {raw!r}")
    return Decimal(s), notes
```

Anti-patterns here: `locale.atof` (process-global mutable state, wrong in a server), `float(s.replace(",", ""))`, and **silently discarding** the ambiguity. `AMOUNT_SEPARATOR_AMBIGUOUS` must reach the decision engine — it is exactly the kind of thing that should push a borderline case to `NEEDS_REVIEW`.

### 1.2 Time: one canonical instant, plus an honest record of what you assumed

Store and compare **UTC-aware** `datetime`. `Asia/Karachi` is UTC+05:00 with no DST and no scheduled transitions — which makes your life much easier than it would be almost anywhere else, but is *not* a licence to store naive datetimes and add 5 hours.

```python
# core/timex.py
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")
UTC = timezone.utc

def require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("naive datetime crossed the core boundary")
    return dt.astimezone(UTC)
```

Never use `datetime.utcnow()`; it is deprecated in 3.12 and returns a *naive* value, which is the single most productive bug factory in this domain. Use `datetime.now(timezone.utc)` — and in `core/`, don't use either: take `now: datetime` as a parameter.

**The hard part is the screenshot's clock.** The screenshot timestamp is not a timestamp; it is a *rendering of a wall clock on an untrusted device*, with several independent unknowns. Model them explicitly instead of pretending you have an instant:

```python
@dataclass(frozen=True, slots=True)
class ClaimedInstant:
    resolved_utc: datetime          # best-effort UTC
    granularity_s: int              # 1, 60 (no seconds shown), 86400 (date only)
    assumed_tz: str                 # "Asia/Karachi"
    tz_stated: bool                 # did the screenshot actually say a zone/offset?
    date_inferred: bool             # did we borrow today's date because none was shown?
```

Concrete traps, all of which have bitten real reconciliation systems:

* **No date on the receipt.** Many wallet SMS/app confirmations show `04:12 PM` only. If you infer the date from upload time you will misdate anything uploaded after midnight. Set `date_inferred=True`, widen tolerance to the day, and never allow `VERIFIED` on an inferred date alone.
* **12-hour clock without AM/PM**, or OCR dropping the meridiem. Produce *two* candidate instants 12h apart and let candidate scoring pick; record `TIME_MERIDIEM_AMBIGUOUS`.
* **Device clock skew.** Phones drift by minutes. This is the whole reason tolerance is a decay curve (§5), not equality.
* **Whole-hour offsets are a red flag, not a match.** If the best delta is within ±90s of an exact multiple of 3600s and the multiple is non-zero, you are almost certainly looking at a timezone/DST artefact or a doctored screenshot. Emit `TIME_WHOLE_HOUR_OFFSET` as an observation; do not silently absorb it into tolerance.

```python
def hour_offset_artifact(delta_s: float, tol_s: float = 90.0) -> int | None:
    hours = round(delta_s / 3600.0)
    return hours if hours != 0 and abs(delta_s - hours * 3600) <= tol_s else None
```

* **Provider vs merchant timestamps differ in meaning** — initiation vs settlement. Your effective tolerance must be at least as wide as that skew, and it belongs in the versioned policy, not in a magic number in `timestamp.py`.

Anti-pattern: comparing a screenshot instant to a ledger instant with `abs(a - b) < timedelta(minutes=5)`. That hard window is discontinuous at 5:00.001, gives no evidence gradient, and provides no way to say "close but not close enough" — the state you most need.

---

## 2. The comparison-level pattern (build this first)

This is the spine of the phase. Splink models each field as a **Comparison** containing **ordered, mutually exclusive ComparisonLevels**, evaluated like an `if/elif/else` chain — first match wins, and every Comparison ends with a catch-all ELSE. The output per field is a *discrete labelled category*, not a raw float.

Adopt this wholesale. Three payoffs:

1. **The explanation is free.** The level's label *is* the UI row: "Sender name — strong match (initials-compatible)". You are not reverse-engineering a float into prose.
2. **The tests are finite.** A float scorer has infinite behaviour; a 5-level comparison has 5 outcomes, and you can write one parametrised test per level.
3. **Thresholds become visible objects.** `JaroWinkler ≥ 0.92` lives in a level definition with a name, not buried in an `if`.

### 2.1 The whole machinery, from scratch

```python
# core/compare/levels.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

@dataclass(frozen=True, slots=True)
class Level:
    code: str                       # STABLE machine id -> golden files, DB, analytics
    label: str                      # human text -> UI (free to reword; code is not)
    score: float                    # 0.0..1.0 evidence strength for this field
    predicate: Callable[[Any, Any, Mapping[str, Any]], bool]

@dataclass(frozen=True, slots=True)
class FieldOutcome:
    field: str
    level_code: str
    label: str
    score: float
    detail: Mapping[str, Any] = field(default_factory=dict)   # raw metrics, for the drawer

@dataclass(frozen=True, slots=True)
class Comparison:
    field: str
    levels: tuple[Level, ...]
    weight: float = 1.0             # relative importance in the aggregate

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError(f"{self.field}: no levels")
        scores = [l.score for l in self.levels]
        if scores != sorted(scores, reverse=True):
            raise ValueError(f"{self.field}: levels must be ordered most->least similar")
        if len(set(l.code for l in self.levels)) != len(self.levels):
            raise ValueError(f"{self.field}: duplicate level codes")

    def evaluate(self, left, right, ctx: Mapping[str, Any]) -> FieldOutcome:
        for lvl in self.levels:
            if lvl.predicate(left, right, ctx):
                return FieldOutcome(self.field, lvl.code, lvl.label, lvl.score,
                                    _metrics(self.field, left, right, ctx))
        raise AssertionError(f"{self.field}: comparison is not total — add an ELSE level")
```

Two invariants worth their weight in gold, both checked in `__post_init__` and again by a Hypothesis test:

* **Monotonic scores.** Level scores must be non-increasing down the list. If a lower level scores higher, your ordering is a lie and the explanation will contradict the number.
* **Totality.** The last level must be an unconditional `lambda *_: True`. Splink requires an `ELSE`; so should you. A `KeyError` in production because no level fired is the worst possible failure mode for an audit trail.

### 2.2 A real comparison

```python
# core/compare/name.py
from rapidfuzz.distance import JaroWinkler

NULL = Level("NAME_MISSING", "Sender name not readable", 0.0,
             lambda a, b, c: not a or not b)

def _jw(a, b, t): return JaroWinkler.normalized_similarity(a, b) >= t

SENDER_NAME = Comparison(
    field="sender_name",
    weight=1.0,
    levels=(
        NULL,
        Level("NAME_EXACT",        "Exact match",                        1.00,
              lambda a, b, c: a == b),
        Level("NAME_MASK_OK",      "Consistent with masked name",        0.85,
              lambda a, b, c: c["mask_consistent"]),
        Level("NAME_STRONG",       "Strong match (minor spelling)",      0.90,
              lambda a, b, c: c["token_score"] >= 0.92),
        Level("NAME_INITIALS",     "Match with initials expanded",       0.80,
              lambda a, b, c: c["initials_compatible"] and c["token_score"] >= 0.80),
        Level("NAME_PARTIAL",      "Partial match (shared surname)",     0.55,
              lambda a, b, c: c["token_score"] >= 0.70),
        Level("NAME_COMMON_ONLY",  "Only a very common name matched",    0.20,
              lambda a, b, c: c["idf_weighted_score"] < 0.30 and c["token_score"] >= 0.70),
        Level("NAME_ELSE",         "No name match",                      0.00,
              lambda a, b, c: True),
    ),
)
```

Note `NAME_MASK_OK`. Pakistani wallet receipts frequently show masked recipient names and masked MSISDNs (`MUHAMMAD A***`, `03XX-XXXXX67`). A comparison that has no level for "the visible part is consistent with the mask" will score a legitimate payment as a mismatch. Model masks as a first-class level, and score it *below* exact — a mask carries genuinely less information.

Anti-pattern: overlapping levels ordered wrong. `NAME_STRONG` at 0.90 sitting below `NAME_MASK_OK` at 0.85 in the list would mean a mask-consistent exact match never reaches `NAME_STRONG` — which is fine and intentional here (mask consistency is checked first because the strings can't be equal), but you must be deliberate about it and assert the resulting order in a test. The `__post_init__` check above will reject the ordering shown; put `NAME_MASK_OK` after `NAME_STRONG` if you want score-monotonicity, or give the mask level 0.92. **Decide, then encode the decision in the constructor check.**

---

## 3. Fuzzy name matching for Pakistani / transliterated names

### 3.1 Normalisation pipeline (deterministic, testable, order matters)

```python
HONORIFICS = frozenset("mr mrs ms miss dr prof engr hafiz haji alhaj mohtarma janab".split())
# NOT stripped: syed, shah, khan, chaudhry, malik, mian, sheikh, mirza, baig
# — these are real name components in Pakistan, not titles. Stripping them destroys signal.

VARIANTS = {  # collapse transliteration families to a canonical token
    "muhammad": "muhammad", "mohammad": "muhammad", "mohammed": "muhammad",
    "mohd": "muhammad", "md": "muhammad", "muhammed": "muhammad", "mohamad": "muhammad",
    "ahmad": "ahmad", "ahmed": "ahmad",
    "abdul": "abdul", "abd": "abdul",
    "ul": "", "bin": "", "binte": "", "s/o": "", "d/o": "", "w/o": "",
}
ACCOUNT_NOISE = frozenset("account acct a/c mobile wallet easypaisa jazzcash raast ltd pvt".split())

def normalize_name(raw: str) -> tuple[str, ...]:
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = s.casefold().replace(".", " ").replace("-", " ")
    s = re.sub(r"[^a-z ]+", " ", s)
    toks = [VARIANTS.get(t, t) for t in s.split()]
    toks = [t for t in toks if t and t not in HONORIFICS and t not in ACCOUNT_NOISE]
    return tuple(toks)
```

Test this function on its own with a table of ~30 real-world pairs. It is the highest-leverage 20 lines in the phase, and it is trivially testable.

### 3.2 Which RapidFuzz scorer, and when

RapidFuzz 3.14.x, Python ≥3.10. The scorers are not interchangeable:

| Scorer | Use it for | Do **not** use it for |
|---|---|---|
| `fuzz.ratio` | two already-normalised single tokens | multi-token names (word order kills it) |
| `fuzz.token_sort_ratio` | same tokens, different order — "Ali Muhammad" vs "Muhammad Ali" | when one side has extra tokens |
| `fuzz.token_set_ratio` | one side has extra tokens — "Muhammad Ali Khan" vs "Ali Khan" | **as your only scorer** — it returns 100 for any subset, so "Muhammad" vs "Muhammad Ali Khan" scores 100 |
| `fuzz.partial_ratio` | substring containment — truncated OCR | short strings; it is far too generous |
| `JaroWinkler.normalized_similarity` | **per-token** comparison; typos, transpositions, prefix agreement | multi-token strings |
| `fuzz.WRatio` | never, in this codebase | it is a heuristic blend; you cannot explain its output to a merchant |

**The recommendation.** Do not use a whole-string scorer as the name score. Splink's own comparator guide recommends Jaro-Winkler for names and a *multi-level* threshold ladder rather than a single cutoff (JW ≥ 0.9 for typos/shortenings, ≥ 0.8 for nicknames, ≥ 0.7 for complex aliases with false-positive risk). Build a **token-alignment score** on top of per-token Jaro-Winkler:

```python
# core/compare/name.py
from rapidfuzz.distance import JaroWinkler

def _tok_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:                       # "m" vs "muhammad"
        return 0.90 if a[0] == b[0] else 0.0             # initials-compatible
    return JaroWinkler.normalized_similarity(a, b)       # prefix_weight default 0.1

def token_alignment(claim: tuple[str, ...], truth: tuple[str, ...],
                    idf: Mapping[str, float]) -> dict:
    """Greedy best-match alignment, IDF-weighted. Deterministic: sort ties by token."""
    remaining = list(truth)
    pairs, used_initial = [], False
    for t in sorted(claim):                              # sorted -> deterministic
        if not remaining:
            break
        best = max(remaining, key=lambda u: (_tok_sim(t, u), u))
        s = _tok_sim(t, best)
        if s > 0.0:
            if len(t) == 1 or len(best) == 1:
                used_initial = True
            pairs.append((t, best, s))
            remaining.remove(best)
    if not pairs:
        return {"token_score": 0.0, "idf_weighted_score": 0.0,
                "initials_compatible": False, "pairs": []}
    plain = sum(s for _, _, s in pairs) / max(len(claim), len(truth))
    wsum = sum(idf.get(t, 1.0) for t, _, _ in pairs) or 1.0
    weighted = sum(s * idf.get(t, 1.0) for t, _, s in pairs) / wsum
    return {"token_score": plain, "idf_weighted_score": weighted,
            "initials_compatible": used_initial, "pairs": pairs}
```

`"Muhammad Ali"` vs `"M. Ali"` → tokens `("muhammad","ali")` vs `("m","ali")` → `ali`↔`ali` = 1.0, `muhammad`↔`m` = 0.90 → `token_score ≈ 0.95`, `initials_compatible=True`. That is the behaviour you wanted, and it is explainable per token, which `token_set_ratio` never is.

### 3.3 Down-weighting common given names — this is not optional here

Splink applies **term-frequency adjustments** precisely because a Fellegi-Sunter model that treats all values as equally informative catastrophically over-weights common ones. In Pakistan, "Muhammad" appears as a component of an enormous share of male names. Two records agreeing on "Muhammad" is nearly zero evidence; two records agreeing on "Zulqarnain" is very strong evidence. A flat scorer gives both the same weight and you will match the wrong transaction.

Cheap, correct implementation: compute IDF **from the merchant's own transaction feed**, which you already have in memory.

```python
import math
from collections import Counter

def build_idf(all_names: Iterable[tuple[str, ...]], floor: float = 0.15) -> dict[str, float]:
    docs = list(all_names)
    n = max(len(docs), 1)
    df = Counter(t for toks in docs for t in set(toks))
    return {t: max(floor, math.log(n / (1 + c)) / math.log(n)) for t, c in df.items()}
```

Ship a **static seed list** as fallback for a cold merchant with 3 transactions (`muhammad, ali, ahmad, khan, hussain, hassan, abdul, syed, fatima, ayesha, bibi` → weight 0.15). Splink's `tf_minimum_u_value` exists for the same reason: keep an extremely-rare value from blowing up the weight. Your `floor` does the same job in the other direction, and a ceiling of 1.0 caps the rare side.

`NAME_COMMON_ONLY` in the comparison above is the level that makes this visible to the merchant: *"Only a very common name matched"* is a genuinely useful thing to show a human.

### 3.4 Phonetics for **blocking**, Jaro-Winkler for **scoring** — never the reverse

`jellyfish` 1.2.1 gives you `metaphone`, `nysiis`, `soundex`, `match_rating_codex`. These are *coarse, English-phonology* encoders. Applied to transliterated Urdu/Arabic names they are noisy — but noisy is fine for a **blocking key**, whose only job is "don't miss the true match", and fatal for a **score**, whose job is "rank candidates correctly".

```python
# core/phonetics.py
import jellyfish

def name_block_keys(tokens: tuple[str, ...], idf: Mapping[str, float]) -> frozenset[str]:
    """Block on the *most distinctive* tokens, not the first token."""
    ranked = sorted(tokens, key=lambda t: -idf.get(t, 1.0))[:2]
    keys = set()
    for t in ranked:
        keys.add("MP:" + jellyfish.metaphone(t))
        keys.add("NY:" + jellyfish.nysiis(t))
    return frozenset(keys)
```

Blocking on "Muhammad" retrieves everything and is useless; blocking on the highest-IDF token is what you want. Metaphone *and* NYSIIS together, unioned, because neither is reliable on transliterations and the union costs nothing.

**But in this domain, name is a weak blocking key anyway.** Your dominant blocking keys are:

1. **Reference ID prefix / suffix** — if the screenshot yields a TID, that alone is a near-unique key.
2. **Time window** — `ledger.ts ∈ [claim.ts − W, claim.ts + W]`, W from policy.
3. **Amount bucket** — exact `minor`, plus a small neighbour set for OCR-plausible confusions.

Name phonetics is the *fourth* key, used to recover candidates when the timestamp is missing or the date was inferred. Say so in `retrieval.py`:

```python
# core/retrieval.py
def candidates(claim, feed, policy, *, now) -> list[LedgerTxn]:
    keys = [
        by_reference(claim, feed),                 # narrowest
        by_time_window(claim, feed, policy.time_window_s),
        by_amount(claim, feed),
        by_name_phonetics(claim, feed),            # recall net
    ]
    seen, out = set(), []
    for group in keys:                             # union, order-stable
        for t in group:
            if t.id not in seen:
                seen.add(t.id); out.append(t)
    return out[: policy.max_candidates]
```

Union, never intersection. Intersecting blocking keys is how you get an `UNMATCHED` on a perfectly good payment whose OCR dropped one digit of the amount.

---

## 4. Numeric tolerance: a decay curve, not a boolean window

recordlinkage implements ElasticSearch-style decay functions for numeric/date comparison, parameterised by `offset` (a free zone of full similarity) and `scale` (the decay rate). The Gaussian one, from its source, is:

```
d' = max(0, |a − b| − offset)
sim = 2 ** (−(d' / scale) ** 2)
```

Which gives the property that makes it easy to reason about and easy to explain: **at distance `offset + scale`, similarity is exactly 0.5.** So `scale` is a "half-similarity distance" — a number you can defend in a design review and configure without a spreadsheet.

```python
# core/compare/decay.py
def gauss(distance: float, offset: float, scale: float) -> float:
    if offset < 0 or scale <= 0:
        raise ValueError("offset >= 0 and scale > 0 required")
    d = max(0.0, abs(distance) - offset)
    return 2.0 ** (-((d / scale) ** 2))
```

Nine lines. Do not add `recordlinkage` (it drags pandas + numpy into your pure layer) — take the formula, cite it in the docstring.

Suggested starting parameters, in policy:

| Signal | offset | scale | sim at offset+scale | Rationale |
|---|---|---|---|---|
| Timestamp, full precision | 120 s | 900 s | 0.5 at 17 min | absorbs device clock skew + initiation/settlement lag |
| Timestamp, minute granularity | 180 s | 900 s | — | receipt showed no seconds |
| Timestamp, date inferred | 6 h | 12 h | — | you don't really know the time |
| Amount (deviation from expected) | 0 | 1% of order | 0.5 at 1% | see §6 — but amount is mostly categorical |

Use `exp` (`2 ** (−d'/scale)`, heavier tail) if you want to be more forgiving far out; use `gauss` when you want near-misses treated as near-certain and far-misses punished hard. **Gaussian is the right default for timestamps**, because its flat top matches the physical reality of clock skew.

Then wrap the continuous score in discrete levels, exactly as in §2:

```python
TIMESTAMP = Comparison("timestamp", weight=0.8, levels=(
    Level("TS_MISSING",  "No usable time on the receipt", 0.0,
          lambda a, b, c: a is None),
    Level("TS_TIGHT",    "Within seconds",                1.00, lambda a,b,c: c["sim"] >= 0.98),
    Level("TS_CLOSE",    "Within a few minutes",          0.85, lambda a,b,c: c["sim"] >= 0.80),
    Level("TS_LOOSE",    "Within the hour",               0.50, lambda a,b,c: c["sim"] >= 0.40),
    Level("TS_HOUR_ART", "Differs by a whole hour",       0.25,
          lambda a,b,c: c["hour_offset"] is not None),
    Level("TS_ELSE",     "Times do not correspond",       0.00, lambda a,b,c: True),
))
```

The continuous score lives in `detail["sim"]` for the evidence drawer; the *decision* consumes the level. Best of both.

Anti-pattern: exposing the raw `sim` float as the headline. `0.7314` means nothing to a merchant. "Within a few minutes" does.

---

## 5. Amount semantics: three axes, not one comparison

This is where most reconciliation systems are wrong, and where ProofPay can be visibly better. There are **three** amounts, and comparing only two of them loses the fraud signal:

* `order.expected` — what the merchant asked for
* `ledger.amount` — **source of truth**, what actually arrived
* `claim.amount` — what the screenshot asserts

Two independent comparisons:

**A. `ledger` vs `expected` — a commercial outcome.**

| Relation | Outcome | Risk | Reason code |
|---|---|---|---|
| `ledger == expected` | exact | none | `AMOUNT_EXACT` |
| `ledger < expected` | **underpayment** | medium | `AMOUNT_UNDERPAID` |
| `ledger > expected` | **overpayment** | low (refund owed) | `AMOUNT_OVERPAID` |

**B. `claim` vs `ledger` — an integrity signal.**

| Relation | Outcome | Risk | Reason code |
|---|---|---|---|
| `claim == ledger` | consistent | none | `CLAIM_CONSISTENT` |
| `claim > ledger` | **claim inflation** — screenshot asserts more than arrived | **high** | `CLAIM_INFLATED` |
| `claim < ledger` | claim deflation — almost always OCR error | low | `CLAIM_DEFLATED` |

Never collapse these into `abs(a - b)`. `abs()` deletes the sign, and the sign is the entire fraud signal. **Claim inflation is directional and must be treated as such.**

```python
# core/compare/amount.py
from enum import StrEnum

class AmountRelation(StrEnum):
    EXACT = "EXACT"; UNDER = "UNDER"; OVER = "OVER"

class ClaimIntegrity(StrEnum):
    CONSISTENT = "CONSISTENT"; INFLATED = "INFLATED"; DEFLATED = "DEFLATED"

@dataclass(frozen=True, slots=True)
class AmountEvidence:
    relation: AmountRelation
    integrity: ClaimIntegrity
    shortfall: Money            # expected - ledger, may be negative
    inflation: Money            # claim - ledger, may be negative
    within_tolerance: bool      # e.g. |shortfall| <= policy.amount_tolerance_minor

def compare_amounts(expected: Money, ledger: Money, claim: Money | None,
                    policy) -> AmountEvidence:
    shortfall = expected - ledger
    relation = (AmountRelation.EXACT if shortfall.minor == 0
                else AmountRelation.UNDER if shortfall.minor > 0
                else AmountRelation.OVER)
    if claim is None:
        integrity, inflation = ClaimIntegrity.CONSISTENT, Money(0, ledger.currency)
    else:
        inflation = claim - ledger
        integrity = (ClaimIntegrity.CONSISTENT if inflation.minor == 0
                     else ClaimIntegrity.INFLATED if inflation.minor > 0
                     else ClaimIntegrity.DEFLATED)
    return AmountEvidence(relation, integrity, shortfall, inflation,
                          abs(shortfall.minor) <= policy.amount_tolerance_minor)
```

Two subtleties worth a fixture each:

* **A small `CLAIM_INFLATED` is not the same as a large one.** `claim − ledger = 100 paisa` on a 5000-rupee order is an OCR artefact. `claim − ledger = 500000 paisa` is an attack. Policy should carry `inflation_material_minor` and `inflation_material_pct`, and the rule table should branch on materiality.
* **Digit-drop inflation.** OCR losing a trailing zero produces *deflation*; a fabricated screenshot typically produces *inflation* with clean round digits. Emit `CLAIM_INFLATED_ROUND` as an observation when the inflation is an exact power-of-ten multiple — a genuinely cheap, genuinely discriminating signal.

---

## 6. Ambiguity as a first-class outcome

Given candidate scores `s₁ ≥ s₂ ≥ …`, a decision needs **two** conditions, not one:

```
accept  ⟺  s₁ ≥ τ_accept  AND  (s₁ − s₂) ≥ τ_margin
```

The margin condition is not academic in this domain. A tea shop selling a Rs. 250 item takes ten identical Rs. 250 payments an hour. Two candidates with `s₁ = 0.94, s₂ = 0.93` are indistinguishable, and silently picking `s₁` **allocates the wrong transaction** — which then fails the DB uniqueness constraint later for the *other* order, producing a confusing false `DUPLICATE`. Ambiguity mishandled in Phase 1 becomes an incoherent bug report in Phase 2.

```python
# core/decide/engine.py
@dataclass(frozen=True, slots=True)
class CandidateRanking:
    scored: tuple[ScoredCandidate, ...]     # sorted desc, ties broken by txn_id for determinism
    @property
    def best(self): return self.scored[0] if self.scored else None
    @property
    def margin(self) -> float:
        if len(self.scored) < 2: return 1.0
        return self.scored[0].score - self.scored[1].score
```

**A dominance escape hatch.** A unique exact reference-ID match should win regardless of margin — the margin rule exists to protect against *interchangeable* candidates, and a unique TID means they are not interchangeable. Encode it explicitly:

```python
def is_dominant(r: CandidateRanking) -> bool:
    exact_ref = [c for c in r.scored if c.outcomes["reference"].level_code == "REF_EXACT"]
    return len(exact_ref) == 1
```

**Determinism of ranking.** Always sort with a total, stable key: `key=lambda c: (-c.score, c.txn.id)`. Floating-point ties plus `list.sort` stability plus a dict-ordered candidate list is a reproducibility bug waiting for a demo. Assert determinism in a test that shuffles the input list and expects an identical `Decision`.

Anti-pattern: treating ambiguity as low confidence and returning `VERIFIED` with `confidence=0.6`. Ambiguity is not "less sure it happened" — it is "sure it happened, unsure *which* one". Those need different UI and different operator action. That is why `NEEDS_REVIEW` with `AMBIGUOUS_CANDIDATES` must be a distinct state, and why your five states already include it.

---

## 7. The decision engine: ordered rules, versioned policy, reason codes

### 7.1 Do not adopt a rules library

You will find `business-rules`, `durable_rules`, `pyDMNrules`, GoRules/ZEN, JSON Logic. **Reject all of them for Phase 1.** Their entire value proposition is *letting non-engineers change rules at runtime without a deploy*. You have four engineers, a three-day window, and a requirement that decisions be reproducible and version-pinned — the opposite trade. A DSL costs you type checking, IDE navigation, stack traces, and Hypothesis coverage, and buys you nothing this week.

A Python list of `Rule` objects gives you first-match semantics, precedence-by-position, full typing, and a trivially serialisable trace. Revisit a library only when a merchant-ops person needs to edit thresholds in a UI — which is a Phase 4 conversation.

### 7.2 Reason codes

```python
# core/decide/reasons.py
from enum import StrEnum

class ReasonCode(StrEnum):
    NO_CANDIDATES              = "NO_CANDIDATES"
    AMBIGUOUS_CANDIDATES       = "AMBIGUOUS_CANDIDATES"
    TXN_ALREADY_ALLOCATED      = "TXN_ALREADY_ALLOCATED"
    CLAIM_INFLATED             = "CLAIM_INFLATED"
    AMOUNT_UNDERPAID           = "AMOUNT_UNDERPAID"
    AMOUNT_OVERPAID            = "AMOUNT_OVERPAID"
    NAME_MISMATCH              = "NAME_MISMATCH"
    TIME_WHOLE_HOUR_OFFSET     = "TIME_WHOLE_HOUR_OFFSET"
    TAMPER_OBSERVATIONS        = "TAMPER_OBSERVATIONS"
    SCREENSHOT_ONLY_EVIDENCE   = "SCREENSHOT_ONLY_EVIDENCE"
    STRONG_FIELD_AGREEMENT     = "STRONG_FIELD_AGREEMENT"
```

**Codes are contracts.** They go into the DB, the API, and the frontend's translation table. Rename the `label`, never the code. Add a code, never repurpose one. `StrEnum` (3.11+) serialises to JSON as a plain string with no `.value` ceremony.

### 7.3 The policy object — every threshold, in one versioned place

```python
# core/decide/policy.py
@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    policy_id: str = "proofpay-policy-1.0.0"
    # retrieval
    time_window_s: int = 86_400
    max_candidates: int = 25
    # decay
    ts_offset_s: float = 120.0
    ts_scale_s: float = 900.0
    ts_offset_s_date_inferred: float = 21_600.0
    ts_scale_s_date_inferred: float = 43_200.0
    # acceptance
    tau_accept: float = 0.82
    tau_reject: float = 0.45
    tau_margin: float = 0.10
    # amounts
    amount_tolerance_minor: int = 0
    inflation_material_minor: int = 5_000        # Rs. 50
    inflation_material_pct: float = 0.01
    # tamper
    tamper_signal_limit: int = 1

    def fingerprint(self) -> str:
        import hashlib, json
        from dataclasses import asdict
        blob = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
```

`fingerprint()` goes into every `Decision`. That is what makes an old decision reconstructable: *this* rule version, *this* policy hash, *these* inputs. Loading the policy from JSON/YAML is a Phase 2 adapter concern — `core` accepts a `DecisionPolicy` and never reads a file.

Anti-pattern: `if score > 0.8:` anywhere in `core/`. Grep for float literals in `decide/` as a lint; there should be none outside `policy.py`.

### 7.4 The rule table

```python
# core/decide/rules_v1.py
RULESET_VERSION = "rules-v1.3.0"

@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    when: Callable[["Context"], bool]
    status: Status
    risk: Risk
    reasons: tuple[ReasonCode, ...]
    note: str

RULES: tuple[Rule, ...] = (
  Rule("R010", lambda c: not c.ranking.scored,
       Status.UNMATCHED, Risk.MEDIUM, (ReasonCode.NO_CANDIDATES,),
       "No merchant transaction plausibly corresponds to this claim."),

  Rule("R020", lambda c: c.best_is_allocated_elsewhere,
       Status.DUPLICATE, Risk.HIGH, (ReasonCode.TXN_ALREADY_ALLOCATED,),
       "That transaction is already allocated to another order."),

  Rule("R030", lambda c: c.material_inflation,
       Status.SUSPICIOUS, Risk.HIGH, (ReasonCode.CLAIM_INFLATED,),
       "The screenshot claims materially more than was received."),

  Rule("R040", lambda c: c.tamper_count > c.policy.tamper_signal_limit
                          and c.best.score < c.policy.tau_accept,
       Status.SUSPICIOUS, Risk.HIGH, (ReasonCode.TAMPER_OBSERVATIONS,),
       "Image observations plus a weak field match."),

  Rule("R050", lambda c: c.best.score >= c.policy.tau_accept
                          and c.ranking.margin < c.policy.tau_margin
                          and not c.dominant,
       Status.NEEDS_REVIEW, Risk.MEDIUM, (ReasonCode.AMBIGUOUS_CANDIDATES,),
       "Two or more transactions match about equally well."),

  Rule("R060", lambda c: c.best.score < c.policy.tau_reject,
       Status.UNMATCHED, Risk.MEDIUM, (ReasonCode.NAME_MISMATCH,),
       "No transaction matched strongly enough."),

  Rule("R070", lambda c: c.best.score >= c.policy.tau_accept
                          and c.amount.relation is AmountRelation.UNDER
                          and not c.amount.within_tolerance,
       Status.NEEDS_REVIEW, Risk.MEDIUM, (ReasonCode.AMOUNT_UNDERPAID,),
       "Matched, but less than the order total was received."),

  Rule("R080", lambda c: c.best.score >= c.policy.tau_accept
                          and c.amount.relation is AmountRelation.OVER,
       Status.VERIFIED, Risk.LOW, (ReasonCode.AMOUNT_OVERPAID,
                                   ReasonCode.STRONG_FIELD_AGREEMENT),
       "Matched; more than the order total was received."),

  Rule("R090", lambda c: c.best.score >= c.policy.tau_accept,
       Status.VERIFIED, Risk.LOW, (ReasonCode.STRONG_FIELD_AGREEMENT,),
       "A merchant transaction matches this claim on all key fields."),

  Rule("R999", lambda c: True,
       Status.NEEDS_REVIEW, Risk.MEDIUM, (), "Insufficient evidence to decide."),
)
```

**Precedence principles, in order of importance:**

1. **Structural impossibility first** (`R010`): no candidates → nothing else can be evaluated.
2. **Safety-negative before safety-positive.** `DUPLICATE` and `SUSPICIOUS` outrank `VERIFIED`. A rule table where a high score can pre-empt a duplicate check is a money-losing bug.
3. **Specific before general.** `R070`/`R080` (amount-qualified verification) sit above the plain `R090`.
4. **A total ELSE (`R999`).** Non-negotiable, same as the comparison ELSE.
5. **Rule IDs are gapped by 10** so you can insert without renumbering, and they never change meaning — `R030` is `R030` forever.

### 7.5 The invariant that must be code, not prose

> No screenshot-derived signal may alone establish that payment occurred.

Make it a **post-condition assertion** in the engine, not a property of rule ordering you hope holds:

```python
def _enforce_invariants(d: Decision, ctx: Context) -> Decision:
    if d.status is Status.VERIFIED and ctx.best is None:
        raise AssertionError("VERIFIED without a ledger transaction")
    if d.status is Status.VERIFIED and ctx.best.txn.source is not Source.MERCHANT_LEDGER:
        raise AssertionError("VERIFIED from non-ledger evidence")
    return d
```

Plus a Hypothesis test: *for any* generated claim and *empty* ledger feed, `decide(...).status is not Status.VERIFIED`. That is the single most valuable test in the project and it takes four lines.

### 7.6 The `Decision` shape

```python
@dataclass(frozen=True, slots=True)
class Decision:
    status: Status                       # VERIFIED|UNMATCHED|SUSPICIOUS|DUPLICATE|NEEDS_REVIEW
    risk: Risk                           # LOW|MEDIUM|HIGH  (ordinal, not a percentage)
    confidence: float                    # 0..1 — confidence in THIS DECISION, not P(fraud)
    reasons: tuple[ReasonCode, ...]
    matched_txn_id: str | None
    fired_rule_id: str
    evidence: tuple[FieldOutcome, ...]   # one per Comparison -> renders directly as UI rows
    observations: tuple[str, ...]        # tamper signals; never a verdict
    ruleset_version: str
    policy_fingerprint: str
    engine_version: str
    evaluated_at: datetime               # the `now` you were handed
```

`confidence` should be derived from **margin and evidence coverage**, never presented as a fraud probability:

```python
def confidence(ranking, evidence, policy) -> float:
    coverage = sum(1 for e in evidence if e.level_code.split("_")[-1] != "MISSING") / len(evidence)
    m = min(1.0, ranking.margin / max(policy.tau_margin, 1e-9))
    return round(min(1.0, 0.5 * ranking.best.score + 0.3 * m + 0.2 * coverage), 3)
```

Ship the formula in the docs. A number nobody can derive is worse than no number.

---

## 8. Threshold selection without a labelled dataset

You have no labels, and you will not have any by demo day. That is fine; be honest about the method.

**Do this, in this order:**

1. **Start from cost asymmetry, not from data.** For a merchant, a false `VERIFIED` (goods handed over, no money) costs the order value; a false `NEEDS_REVIEW` costs 30 seconds. That asymmetry is maybe 100:1, so set `τ_accept` conservatively high and let `NEEDS_REVIEW` absorb the uncertainty. This is the classic three-band accept / clerical-review / reject design from record-linkage practice, and it is the right shape here.

2. **Write ~25 hand-labelled scenario fixtures first, then fit thresholds to them.** Four people can produce 25 scenarios in an hour: exact match, name initials, masked name, timestamp 3 min off, timestamp 1 h off, underpayment by Rs. 50, claim inflated by Rs. 5000, two identical Rs. 250 candidates, transaction already allocated, no ledger at all, date-inferred receipt, and so on. Store them as a YAML/JSON table with an `expected_status`. This is a labelled dataset — it is just small and hand-made, which is exactly right for a hackathon.

3. **Sweep, and pick a plateau not a peak.** Vary `τ_accept` over `0.60 … 0.95` in steps of `0.01`, count fixture failures, and choose the **midpoint of the widest interval where the count is minimal**. A threshold sitting on a cliff edge is a threshold that will move under you.

```python
def sweep(fixtures, base_policy, field="tau_accept", grid=None):
    grid = grid or [round(x / 100, 2) for x in range(60, 96)]
    return {v: sum(decide(**f.inputs, policy=replace(base_policy, **{field: v})).status
                   != f.expected_status for f in fixtures) for v in grid}
```

4. **Sanity-check the score distribution on synthetic non-matches.** Pair every claim with every *wrong* ledger transaction. That gives you a free empirical distribution of "definitely not a match" scores. `τ_reject` should sit above that distribution's 99th percentile. No labels required.

**Anti-patterns:**

* Tuning on the five screenshots you'll use in the demo. It will look perfect and generalise to nothing. Keep two demo screenshots strictly out of the fixture set as a holdout.
* Baking a threshold into a comparison level and a *different* one into a rule. Every number lives in `DecisionPolicy`.
* Reporting a threshold to 4 decimal places from 25 fixtures. `0.82`, not `0.8237`.
* Changing a threshold without bumping `policy_id`. Old decisions become unexplainable.

---

## 9. Testing pure decision logic

### 9.1 Parametrised decision tables (the workhorse)

```python
# tests/test_rules.py
@dataclass(frozen=True)
class Case:
    id: str
    scenario: Scenario
    expect_status: Status
    expect_rule: str
    expect_reasons: tuple[ReasonCode, ...] = ()

CASES = [
    Case("exact-match",       S.exact(),                 Status.VERIFIED,     "R090",
         (ReasonCode.STRONG_FIELD_AGREEMENT,)),
    Case("initials-name",     S.name("M. Ali"),          Status.VERIFIED,     "R090"),
    Case("txn-reused",        S.allocated_elsewhere(),   Status.DUPLICATE,    "R020"),
    Case("claim-inflated",    S.inflate(Money(500_000)), Status.SUSPICIOUS,   "R030"),
    Case("two-identical",     S.twin_candidates(),       Status.NEEDS_REVIEW, "R050"),
    Case("empty-ledger",      S.no_ledger(),             Status.UNMATCHED,    "R010"),
    Case("underpaid-50",      S.short(Money(5_000)),     Status.NEEDS_REVIEW, "R070"),
]

@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_decision_table(case):
    d = decide(**case.scenario.inputs(), policy=POLICY, now=FIXED_NOW)
    assert (d.status, d.fired_rule_id) == (case.expect_status, case.expect_rule)
    assert set(case.expect_reasons) <= set(d.reasons)
```

Asserting `fired_rule_id` as well as `status` is what catches "right answer, wrong reason" — a rule reordering that happens to produce the same status today and the wrong one tomorrow.

### 9.2 Golden files

Use **syrupy** (`pip install syrupy`; zero-dependency pytest plugin, `assert x == snapshot`, JSON serialiser, `--snapshot-update`, and it *fails on a missing snapshot* rather than silently creating one — which is the behaviour you want in CI).

```python
def test_decision_golden(snapshot):
    d = decide(**SCENARIOS["claim-inflated"].inputs(), policy=POLICY, now=FIXED_NOW)
    assert asdict(d) == snapshot(name="claim-inflated")
```

Review snapshot diffs in code review. A change to a level label showing up as a diff in 30 snapshots is a *feature* — it tells you what the merchant will now see.

*Cheap version if you'd rather not add a dep:* `tests/golden/*.json` plus a 12-line helper with a `PROOFPAY_UPDATE_GOLDEN=1` env switch. Perfectly adequate.

**Trap:** golden files capture `policy_fingerprint` and `evaluated_at`. Pin `now = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)` as a module constant, and treat a fingerprint diff as a *required* signal — if a policy change didn't move the fingerprint, your fingerprint is broken.

### 9.3 Hypothesis for the scorers

Hypothesis 6.165.x, Python ≥3.10. Property tests belong on the *scorers and level machinery*, not the rule table (the rule table is finite; enumerate it).

```python
from hypothesis import given, strategies as st

names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30)

@given(names, names)
def test_name_score_bounded_and_symmetric(a, b):
    x, y = token_alignment(normalize_name(a), normalize_name(b), {})["token_score"], \
           token_alignment(normalize_name(b), normalize_name(a), {})["token_score"]
    assert 0.0 <= x <= 1.0
    assert x == pytest.approx(y, abs=1e-9)      # symmetry

@given(names)
def test_identity(a):
    t = normalize_name(a)
    assume(t)
    assert token_alignment(t, t, {})["token_score"] == pytest.approx(1.0)

@given(st.floats(0, 1e6, allow_nan=False), st.floats(0, 1e6, allow_nan=False))
def test_gauss_monotone(d1, d2):
    assume(d1 <= d2)
    assert gauss(d1, 120, 900) >= gauss(d2, 120, 900) - 1e-12

@given(st.builds(Scenario.arbitrary))
def test_exactly_one_level_fires(s):
    out = SENDER_NAME.evaluate(s.left, s.right, s.ctx)      # raises if none fires
    assert out.level_code in {l.code for l in SENDER_NAME.levels}

@given(st.builds(Scenario.arbitrary))
def test_screenshot_alone_never_verifies(s):
    assert decide(claim=s.claim, feed=(), policy=POLICY, now=FIXED_NOW).status \
        is not Status.VERIFIED
```

Symmetry is the property most likely to actually fail — greedy token alignment is not symmetric by construction. If the test fails, that is a real finding: sort the shorter list, or take `max` of both directions.

### 9.4 Boundary behaviour

Pick a comparison convention — **`>=` everywhere** — write it in the module docstring, and test all three points:

```python
@pytest.mark.parametrize("delta,expect", [(-1e-9, Status.NEEDS_REVIEW),
                                          (0.0,   Status.VERIFIED),
                                          (1e-9,  Status.VERIFIED)])
def test_tau_accept_boundary(delta, expect):
    ...
```

And a determinism test:

```python
def test_deterministic_under_candidate_shuffle():
    base = decide(claim=C, feed=FEED, policy=POLICY, now=FIXED_NOW)
    for seed in range(20):
        shuffled = random.Random(seed).sample(FEED, len(FEED))
        assert asdict(decide(claim=C, feed=shuffled, policy=POLICY, now=FIXED_NOW)) == asdict(base)
```

---

## 10. Python code shape

**Frozen dataclasses for domain types; pydantic only at the boundary.** Use `@dataclass(frozen=True, slots=True, kw_only=True)`:

* `frozen=True` → hashable, safe to share across candidates, no accidental mutation mid-pipeline.
* `slots=True` → real memory/attribute-speed win, and it makes typos raise `AttributeError` instead of silently creating a field.
* `kw_only=True` → `PaymentClaim(amount=..., sender=...)` at every call site; positional args on a 9-field claim is how you swap `claim` and `ledger` amounts and invert your fraud logic.

Pydantic v2 is excellent — at the **HTTP and adapter boundary** (Phase 2/3), where untrusted JSON arrives. Inside `core/`, it buys you validation you don't need (the data was already validated on the way in) and costs you import weight, a validation-error surface, and friction with Hypothesis. Validate once at the edge, then hand pure frozen dataclasses inward. Bridging is a one-liner: `PaymentClaimIn.model_validate(body).to_domain()`.

**Function signatures.** Every entry point takes its world explicitly:

```python
def decide(*, claim: PaymentClaim, order: Order, feed: Sequence[LedgerTxn],
           allocations: Mapping[str, str], policy: DecisionPolicy,
           observations: Sequence[str] = (), now: datetime) -> Decision: ...
```

`feed` is a `Sequence`, not a query. `allocations` is a `Mapping[txn_id -> order_id]`, not a DB session. Phase 2's repository loads them and passes them in. That keeps the DB constraint as the *enforcer* of allocation uniqueness while the engine merely *observes and explains* the conflict — exactly the separation you committed to.

**Dependency direction:** `api → services → core`. `core` imports nothing above it. One arrow, no exceptions, enforced by the test in §0.

---

## Anti-patterns, consolidated

| Anti-pattern | Why it bites here |
|---|---|
| `float` for money | equality breaks exactly at the boundaries you test |
| `datetime.utcnow()` / naive datetimes | deprecated in 3.12, returns naive, double-converts on `astimezone` |
| `datetime.now()` inside `core/` | destroys reproducibility and golden files |
| Hard tolerance window (`abs(Δ) < 5min`) | discontinuous, no gradient, no "close but not enough" state |
| `abs(claim − ledger)` | deletes the sign — and the sign *is* the fraud signal |
| `fuzz.WRatio` / `token_set_ratio` alone as the name score | unexplainable; `token_set_ratio` returns 100 for any subset |
| Flat name weighting | "Muhammad" matches everything in Pakistan |
| Phonetics as a *score* | metaphone/NYSIIS are English-phonology and coarse; blocking only |
| Intersecting blocking keys | one OCR digit error → false `UNMATCHED` |
| Best-score-wins with no margin check | wrong allocation on identical-amount transactions |
| Threshold literals scattered in code | unversioned, untestable, unexplainable |
| Reason codes reworded in place | breaks the DB, the API, and every past decision |
| Comparison with no ELSE level | `KeyError` in the audit trail |
| `VERIFIED` reachable without a ledger row | violates the core architectural commitment |
| Adopting a rules DSL for a 3-day build | pays a runtime-editability cost you're not collecting |
| Tuning thresholds on the demo screenshots | perfect demo, zero generalisation |

---

## What to cut if you run out of time

Keep, in strict priority order: `Money` + `timex`, the `Comparison`/`Level` machinery, the amount-semantics table, the ordered rule table with `R999`, the `DecisionPolicy` with a fingerprint, the parametrised decision-table test, and the "screenshot alone never verifies" property test.

Defer without shame: IDF computed from the live feed (ship the static seed list), NYSIIS alongside metaphone (metaphone alone is fine), syrupy (hand-rolled golden JSON is fine), the full threshold sweep (25 fixtures + judgement is fine), and `partial_token_*` scorers entirely.

---

## References

- [Splink — Comparisons and comparison levels](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/comparisons_and_comparison_levels.html)
- [Splink — Comparison Level Library](https://moj-analytical-services.github.io/splink/api_docs/comparison_level_library.html)
- [Splink — Choosing string comparators](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/choosing_comparators.html)
- [Splink — Term frequency adjustments](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html)
- [recordlinkage — Comparing (numeric/date decay methods)](https://recordlinkage.readthedocs.io/en/latest/ref-compare.html) and [`algorithms/numeric.py`](https://github.com/J535D165/recordlinkage/blob/master/recordlinkage/algorithms/numeric.py)
- [Elasticsearch — Decay functions](https://www.elastic.co/docs/reference/query-languages/esql/functions-operators/search-functions/decay)
- [RapidFuzz — fuzz scorers](https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html), [process](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html), [JaroWinkler](https://rapidfuzz.github.io/RapidFuzz/Usage/distance/JaroWinkler.html) (3.14.5, Python ≥3.10)
- [jellyfish — Functions](https://jamesturk.github.io/jellyfish/functions/) (1.2.1, Python ≥3.9)
- [Hypothesis on PyPI](https://pypi.org/project/hypothesis/) (6.165.x, Python ≥3.10) and [Metamorphic testing](https://www.seifertm.de/blog/metamorphic-testing/)
- [syrupy — pytest snapshot plugin](https://syrupy-project.github.io/syrupy/)
- [Pydantic — Models & config](https://docs.pydantic.dev/latest/concepts/models/) and [Dataclasses](https://docs.pydantic.dev/latest/concepts/dataclasses/)
- [Storing currency values: data types, caveats, best practices](https://cardinalby.github.io/blog/post/best-practices/storing-currency-values-data-types/)
- [Explainable entity resolution: confidence, thresholds, audit trails](https://tilores.io/content/explainable-entity-resolution-confidence-thresholds-audit/)
- [ONS — Developing standard tools for data linkage (clerical review bands)](https://www.ons.gov.uk/methodology/methodologicalpublications/generalmethodology/onsworkingpaperseries/developingstandardtoolsfordatalinkagefebruary2021)
- [Asia/Karachi time zone (PKT, UTC+5, no DST)](https://timezonedb.com/time-zones/Asia/Karachi); [ISO 4217 minor units](https://docs.datatrans.ch/docs/currency-codes)

---

## Definition of done

**Structure and purity**

- [ ] `proofpay/core/` exists with the module layout above and imports nothing from `api/`, `db/`, or any adapter.
- [ ] `test_core_has_no_io_imports` and `test_core_never_reads_the_clock` pass in CI.
- [ ] `decide()` takes `now: datetime` as a required keyword argument; no clock read anywhere in `core/`.
- [ ] All domain types are `@dataclass(frozen=True, slots=True, kw_only=True)`; no pydantic import inside `core/`.

**Money and time**

- [ ] `Money` stores `int` minor units; `__post_init__` rejects `float`/`bool`; `Decimal` appears only inside `from_major`.
- [ ] `grep -rn "float(" proofpay/core/money.py` returns nothing.
- [ ] `parse_amount_text` handles `Rs.`, `PKR`, `/-`, `,` and `.` separators, NFKC-folded Arabic-Indic digits, and emits `AMOUNT_OCR_GLYPH_FIXUP` / `AMOUNT_SEPARATOR_AMBIGUOUS` notes. ≥15 parametrised cases.
- [ ] Every datetime crossing into `core` is checked by `require_aware`; a naive datetime raises.
- [ ] `ClaimedInstant` carries `granularity_s`, `assumed_tz`, `tz_stated`, `date_inferred`, and tolerance widens when `date_inferred` is true.
- [ ] `hour_offset_artifact` implemented; `TIME_WHOLE_HOUR_OFFSET` reaches the decision and has a fixture.

**Comparison levels**

- [ ] `Comparison.__post_init__` rejects non-monotonic level scores and duplicate level codes.
- [ ] Every `Comparison` ends in an unconditional ELSE level; a Hypothesis test proves exactly one level fires for arbitrary input.
- [ ] ≥4 comparisons implemented: `sender_name`, `timestamp`, `amount`, `reference`. `sender_name` includes a masked-name level.
- [ ] Each `Level` has a stable `code` **and** a separate human `label`; `FieldOutcome.detail` carries the raw metric.

**Name matching**

- [ ] `normalize_name` strips honorifics, collapses the Muhammad/Mohammad/Md family, and preserves Khan/Syed/Chaudhry. ≥30 table cases.
- [ ] `token_alignment` returns `token_score`, `idf_weighted_score`, `initials_compatible`, and per-token `pairs`.
- [ ] `"Muhammad Ali"` vs `"M. Ali"` produces `NAME_INITIALS` or better; asserted in a test.
- [ ] IDF built from the merchant feed with a static seed fallback and a floor; `NAME_COMMON_ONLY` fires for a common-name-only agreement.
- [ ] Phonetic encoders appear **only** in `phonetics.py`, used for blocking, never in a score.

**Retrieval and ambiguity**

- [ ] Candidate retrieval unions (never intersects) reference / time / amount / phonetic keys and is capped by `policy.max_candidates`.
- [ ] Ranking sorts by `(-score, txn_id)`; `test_deterministic_under_candidate_shuffle` passes.
- [ ] `CandidateRanking.margin` implemented; `AMBIGUOUS_CANDIDATES → NEEDS_REVIEW` has a two-identical-candidates fixture.
- [ ] Unique-exact-reference dominance overrides the margin rule, with its own fixture.

**Amount semantics**

- [ ] `AmountEvidence` distinguishes UNDER / EXACT / OVER **and** CONSISTENT / INFLATED / DEFLATED as independent axes.
- [ ] Underpayment, overpayment, and claim inflation map to three different statuses/risks; one fixture each.
- [ ] Materiality thresholds for inflation live in policy; an immaterial inflation does **not** produce `SUSPICIOUS`.

**Decision engine**

- [ ] `ReasonCode` is a `StrEnum`; no code is reworded or repurposed after first commit.
- [ ] `DecisionPolicy` holds every threshold; `grep -nE "0\.[0-9]" proofpay/core/decide/*.py` matches only `policy.py`.
- [ ] `policy.fingerprint()` and `RULESET_VERSION` are stamped on every `Decision`.
- [ ] `RULES` is an ordered tuple ending in a total `R999`; rule IDs gapped by 10 and stable.
- [ ] Every rule carries `status`, `risk`, `reasons`, and a merchant-readable `note`.
- [ ] `Decision` carries status + risk + confidence + reasons + `fired_rule_id` + per-field `evidence` + `observations`.
- [ ] `confidence` is documented as decision confidence, not a fraud probability; the formula is in the docstring.
- [ ] `_enforce_invariants` raises if `VERIFIED` is reached without a merchant-ledger transaction, **and** a Hypothesis test proves an empty feed can never yield `VERIFIED`.
- [ ] Tamper observations are strings in `observations`, never a status by themselves.

**Calibration**

- [ ] ≥25 scenario fixtures in a data file with `expected_status` and `expected_rule`.
- [ ] Two demo screenshots held out of the fixture set.
- [ ] `sweep()` run once for `tau_accept` and `tau_margin`; chosen values documented as plateau midpoints with two decimal places.
- [ ] `tau_reject` justified against the synthetic non-match score distribution.

**Testing**

- [ ] `pytest` runs the whole `core` suite in under 5 seconds with no network, no DB, no filesystem writes outside `__snapshots__`.
- [ ] Parametrised decision-table test asserts `(status, fired_rule_id)` and reason-code subset for every fixture.
- [ ] Golden snapshots committed for ≥8 representative decisions; `FIXED_NOW` pinned as a constant.
- [ ] Hypothesis properties passing: score bounds, symmetry, identity, gauss monotonicity, exactly-one-level, screenshot-alone-never-verifies.
- [ ] Boundary tests at `τ − ε`, `τ`, `τ + ε` for `tau_accept`, `tau_reject`, `tau_margin`; `>=` convention documented in the module docstring.
- [ ] Coverage on `core/decide/` ≥ 95%, with every rule ID hit by at least one test.