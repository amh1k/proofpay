"""Deterministic normalisation of OCR text: amounts, names, reference ids.

Everything here is a pure function of its input. Same string in, same tuple out,
forever - which is what lets a stored decision be replayed years later.

Two design rules run through the module:

* **Never guess silently.** Where the input is genuinely ambiguous (is `1.500`
  one thousand five hundred, or one and a half rupees?) the ambiguity is
  resolved *and reported* as a note, so the decision engine can push a
  borderline case to review instead of quietly betting.
* **Never use locale.** `locale.atof` is process-global mutable state and is
  wrong in a server. Separator roles are decided by position, not by guessing a
  country.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from decimal import Decimal

from proofpay.core.money import DEFAULT_CURRENCY, Money
from proofpay.core.reasons import ObservationCode

__all__ = [
    "ACCOUNT_NOISE",
    "COMMON_NAME_TOKENS",
    "HONORIFICS",
    "NAME_VARIANTS",
    "fold_digits",
    "fold_token",
    "nfkc",
    "normalize_name",
    "normalize_name_many",
    "normalize_reference",
    "parse_amount_money",
    "parse_amount_text",
    "reference_confusable_key",
    "strip_currency_words",
]


# --------------------------------------------------------------------------
# Text folding
# --------------------------------------------------------------------------

def nfkc(raw: str) -> str:
    """NFKC-fold, drop bidi marks, and collapse whitespace.

    NFKC folds full-width forms, ligatures and compatibility variants. It does
    **not** convert Arabic-Indic digits to ASCII - a widely repeated claim that
    is simply false; `fold_digits` does that job.
    """
    s = unicodedata.normalize("NFKC", raw)
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")  # NBSP, RLM, LRM
    return re.sub(r"\s+", " ", s).strip()


def fold_digits(s: str) -> tuple[str, bool]:
    """Map every Unicode decimal digit to its ASCII equivalent.

    Returns `(folded, changed)`. Receipts from Urdu-locale devices print
    Arabic-Indic (U+0660..) or Eastern Arabic-Indic (U+06F0..) digits. `Decimal`
    happens to accept them, but every regex, slice and log line downstream is
    written for ASCII, so fold once here rather than trusting luck later.
    """
    out: list[str] = []
    changed = False
    for ch in s:
        if ch.isdigit() and not ch.isascii():
            out.append(str(unicodedata.digit(ch)))
            changed = True
        else:
            out.append(ch)
    return "".join(out), changed


# --------------------------------------------------------------------------
# Amounts
# --------------------------------------------------------------------------

# OCR reads letters for digits inside numeric fields. The repair is applied to
# the numeric run only - never to the surrounding text, or "Total" would become
# "T0ta1" and contribute two phantom digits.
_DIGIT_FIXUPS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8"})
_GLYPH_CHARS = re.compile(r"[OolISB]")
_STRIP = re.compile(r"[^\d.,]")

# A numeric run: digits and their OCR look-alikes, plus separators.
_NUM_RUN = re.compile(r"[0-9OolISB][0-9OolISB.,]*")

# Currency words and trailing decorations. Removed first so that the "S" of
# "RS." can never be repaired into a 5.
_CURRENCY_WORDS = re.compile(
    r"(?i)(?:\bpkr\b|\brs\.?|\brupees?\b|\bpaisas?\b|\bonly\b|/\s*-|₨|﷼)"
)

# "12 345" - a space used as a thousands separator, joined before parsing.
_SPACE_GROUPED = re.compile(r"(?<=\d)[  ](?=\d{3}(?:\D|$))")


def strip_currency_words(s: str) -> str:
    """Remove currency markers so glyph repair only ever touches the number."""
    return _CURRENCY_WORDS.sub(" ", s)


def _best_numeric_run(s: str) -> str:
    """Pick the run most likely to be the amount: most digits, then longest.

    Receipt lines carry labels ("Total:", "Bill"), and a label can contain
    characters that look like digits to the repair table. Choosing the
    digit-richest run first, and repairing only that run, keeps the label out of
    the number. Ties resolve to the leftmost run, which is deterministic.
    """
    best = ""
    best_key = (0, 0)
    for run in _NUM_RUN.findall(s):
        digits = sum(ch.isdigit() for ch in run)
        # A run of pure look-alikes ("o" in "no digits") is prose, not an
        # amount. Requiring one real digit is what keeps repair from inventing
        # a number out of a word.
        if digits == 0:
            continue
        key = (digits, len(run))
        if key > best_key:
            best, best_key = run, key
    return best


def parse_amount_text(raw: str) -> tuple[Decimal, list[str]]:
    """Parse an amount out of OCR text.

    Returns `(value, notes)` where `notes` are `ObservationCode` strings for the
    evidence trail. This is the only function in `core` that touches `Decimal`;
    prefer `parse_amount_money`, which converts at the boundary so `Decimal`
    never travels further into the engine.

    Handles, with a fixture for each: `Rs. 1,500`, `PKR 1,500.00`, `Rs 1500/-`,
    U+066C as a thousands separator, Arabic-Indic digits, `Rs. l,50O`
    (letter-for-digit substitution) and the genuinely ambiguous `1.500`.

    Raises `ValueError` when the text holds no digits at all. An unreadable
    amount is a *missing field*, and the caller must record it as such rather
    than receive a fabricated zero.
    """
    notes: list[str] = []
    s = nfkc(raw)
    s, non_ascii_digits = fold_digits(s)
    if non_ascii_digits:
        notes.append(ObservationCode.AMOUNT_NON_ASCII_DIGITS)
    # Arabic separators carry the same roles as "," and ".".
    s = s.replace("٬", ",").replace("٫", ".")
    s = strip_currency_words(s)
    s = _SPACE_GROUPED.sub("", s)

    s = _best_numeric_run(s)
    if _GLYPH_CHARS.search(s):
        s = s.translate(_DIGIT_FIXUPS)
        notes.append(ObservationCode.AMOUNT_OCR_GLYPH_FIXUP)
    s = _STRIP.sub("", s).strip(".,")

    # Decide separator roles by position, never by locale guessing.
    if "," in s and "." in s:
        # The rightmost separator is the decimal point; the other groups digits.
        if s.rfind(".") > s.rfind(","):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # 1,500 and 1,500,000 group digits; 1,50 is a decimal comma.
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        # "1.500" is European grouping *or* one and a half rupees. Grouping is
        # the better bet on a rupee receipt, but the ambiguity is real and has
        # to reach the decision engine rather than die here.
        s = s.replace(".", "")
        notes.append(ObservationCode.AMOUNT_SEPARATOR_AMBIGUOUS)
    if not s or not any(ch.isdigit() for ch in s):
        raise ValueError(f"no digits in {raw!r}")
    if s.count(".") > 1:
        raise ValueError(f"unparseable amount {raw!r}")
    return Decimal(s), notes


def parse_amount_money(raw: str, currency: str = DEFAULT_CURRENCY) -> tuple[Money, tuple[str, ...]]:
    """`parse_amount_text`, converted to `Money` at the boundary.

    This is the function every other layer should call: the point at which
    `Decimal` stops existing and integer minor units take over.
    """
    value, notes = parse_amount_text(raw)
    return Money.from_major(value, currency), tuple(notes)


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

#: Titles carrying no identity. Stripping these is safe.
HONORIFICS = frozenset(["mr", "mrs", "ms", "miss", "dr", "prof", "engr", "hafiz", "haji", "alhaj", "mohtarma", "janab"])

# NOT stripped, deliberately: syed, shah, khan, chaudhry, malik, mian, sheikh,
# mirza, baig. In Pakistan these are real name components, not titles, and
# stripping them deletes the signal that tells two customers apart.

#: Transliteration families collapsed onto one canonical token. An empty value
#: means "drop this token": connectors carry no identity.
#: Name components so common in Pakistan that two records agreeing on one
#: is close to no evidence at all. One list, read by both consumers: the
#: retrieval index uses it to avoid *blocking* on a ubiquitous token, and
#: the name comparison uses it to avoid *scoring* one. A merchant with three
#: transactions cannot possibly establish that `Muhammad` is common, and a
#: measured frequency on that feed would conclude the opposite, so both
#: consumers pin these to their floor regardless of what the feed says.
COMMON_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "muhammad", "ali", "ahmad", "khan", "hussain", "hassan",
        "abdul", "syed", "fatima", "ayesha", "bibi",
    }
)


NAME_VARIANTS: dict[str, str] = {
    "muhammad": "muhammad",
    "mohammad": "muhammad",
    "mohammed": "muhammad",
    "muhammed": "muhammad",
    "mohamad": "muhammad",
    "mohamed": "muhammad",
    "mohd": "muhammad",
    "md": "muhammad",
    "ahmad": "ahmad",
    "ahmed": "ahmad",
    "abdul": "abdul",
    "abd": "abdul",
    "hasan": "hassan",
    "hassan": "hassan",
    "husain": "hussain",
    "hussain": "hussain",
    "hussein": "hussain",
    "ul": "",
    "bin": "",
    "binte": "",
    "binti": "",
}

#: Wallet chrome that rides along with a name field on a receipt.
ACCOUNT_NOISE = frozenset(
    ["account", "acct", "ac", "mobile", "wallet", "easypaisa", "jazzcash", "raast", "ltd", "pvt", "limited", "bank"]
)

_RELATION = re.compile(r"(?i)\b[sdw]\s*/\s*o\b")


def fold_token(token: str) -> str:
    """Collapse one token onto its canonical transliteration."""
    return NAME_VARIANTS.get(token, token)


def normalize_name(raw: str) -> tuple[str, ...]:
    """Normalise a name into an ordered tuple of comparable tokens.

    Order matters and every step earns its place:

    1. NFKD + ASCII fold - drops diacritics, so an accented `Fatima` meets a
       plain one.
    2. Casefold, and treat `.` and `-` as separators so `M.Ali` yields two tokens.
    3. Remove `s/o`, `d/o`, `w/o` *before* punctuation is stripped; otherwise
       they survive as stray `s` and `o` tokens and pollute the alignment.
    4. Drop everything that is not a letter or a space.
    5. Fold transliteration variants, then drop honorifics and wallet chrome.

    Returns `()` when a name normalises to nothing - a legitimate outcome for a
    name written purely in Urdu script, and one the caller must treat as a
    missing field rather than as a mismatch.
    """
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = s.casefold().replace(".", " ").replace("-", " ")
    s = _RELATION.sub(" ", s)
    s = re.sub(r"[^a-z ]+", " ", s)
    toks = [fold_token(t) for t in s.split()]
    return tuple(t for t in toks if t and t not in HONORIFICS and t not in ACCOUNT_NOISE)


def normalize_name_many(raws: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    """Normalise a feed of names - the input to IDF construction."""
    return tuple(normalize_name(r) for r in raws)


# --------------------------------------------------------------------------
# Reference ids
# --------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_REF_LABEL = re.compile(r"^(?:TRANSACTION\s*ID|TID|TXN|TRX|REF)[:#\s]*")

# Reference ids mix letters and digits, so the amount-style repair table would
# be destructive here. Instead fold both members of each confusable pair onto
# one representative and compare in that space.
_CONFUSABLE = str.maketrans(
    {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"}
)


def normalize_reference(raw: str) -> str:
    """Upper-case, alphanumeric-only form of a transaction reference.

    Providers print the same id as `TID: 1234-5678`, `1234 5678` and
    `tid12345678`; the punctuation and the label carry no information.
    """
    s = nfkc(raw).upper()
    s, _ = fold_digits(s)
    s = _REF_LABEL.sub("", s)
    return _NON_ALNUM.sub("", s)


def reference_confusable_key(raw: str) -> str:
    """Blocking key that survives OCR letter/digit confusion.

    `O`/`0`, `I`/`1`, `S`/`5` and friends collapse onto one representative, so a
    misread reference still retrieves its true transaction. Use it for retrieval
    and for a "matches except for confusable glyphs" level - never as a claim
    that two references are equal.
    """
    return normalize_reference(raw).translate(_CONFUSABLE)
