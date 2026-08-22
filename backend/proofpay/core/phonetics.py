"""Phonetic keys for blocking - never for scoring.

`jellyfish`'s metaphone and NYSIIS are coarse **English-phonology** encoders.
Applied to transliterated Urdu/Arabic names they are noisy. Noisy is perfectly
acceptable for a blocking key, whose only job is "do not miss the true match",
and fatal for a score, whose job is "rank candidates correctly". Jaro-Winkler
does the scoring; these functions must never appear in a comparison level.

Blocking on a common token retrieves the whole feed and is useless, so keys are
built from the *most distinctive* tokens by IDF, not from the first token.

Note also that in this domain the name is only the fourth-best blocking key,
behind reference id, time window and amount. It earns its place as the recall
net for claims whose timestamp is missing or whose date had to be inferred.
"""

from __future__ import annotations

from collections.abc import Mapping

import jellyfish

__all__ = ["name_block_keys", "token_phonetic_keys"]

#: How many tokens of a name contribute blocking keys. Two is enough to keep
#: recall high without turning every claim into a full scan.
_MAX_BLOCK_TOKENS = 2


def token_phonetic_keys(token: str) -> tuple[str, ...]:
    """Prefixed metaphone and NYSIIS codes for one normalised token.

    Both encoders, unioned: neither is reliable on transliterations, they fail
    on different names, and the union costs nothing. Codes are prefixed so a
    metaphone code can never collide with a NYSIIS code that happens to spell
    the same letters.
    """
    if not token:
        return ()
    keys: list[str] = []
    mp = jellyfish.metaphone(token)
    if mp:
        keys.append("MP:" + mp)
    ny = jellyfish.nysiis(token)
    if ny:
        keys.append("NY:" + ny)
    return tuple(keys)


def name_block_keys(tokens: tuple[str, ...], idf: Mapping[str, float]) -> frozenset[str]:
    """Blocking keys for a normalised name, drawn from its rarest tokens.

    `idf` maps token to inverse document frequency (see the retrieval layer);
    an unknown token is treated as maximally distinctive, which is the
    recall-safe direction. Ties break on the token itself so the selection is
    deterministic for a given name.
    """
    ranked = sorted(tokens, key=lambda t: (-idf.get(t, 1.0), t))[:_MAX_BLOCK_TOKENS]
    keys: set[str] = set()
    for token in ranked:
        keys.update(token_phonetic_keys(token))
    return frozenset(keys)
