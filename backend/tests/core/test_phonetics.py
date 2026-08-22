"""Phonetic keys are a recall net for blocking, never a score."""

from proofpay.core.normalize import normalize_name
from proofpay.core.phonetics import name_block_keys, token_phonetic_keys


class TestTokenPhoneticKeys:
    def test_both_encoders_contribute_prefixed_keys(self):
        keys = token_phonetic_keys("zulqarnain")
        assert any(k.startswith("MP:") for k in keys)
        assert any(k.startswith("NY:") for k in keys)

    def test_empty_token_yields_nothing(self):
        assert token_phonetic_keys("") == ()

    def test_transliteration_spellings_share_a_key(self):
        # The whole point of the recall net: two spellings, one bucket.
        assert set(token_phonetic_keys("zulqarnain")) & set(token_phonetic_keys("zulqarnayn"))


class TestNameBlockKeys:
    def test_blocks_on_the_rarest_tokens_not_the_first(self):
        # "Muhammad" retrieves the whole feed; "Zulqarnain" retrieves one row.
        tokens = normalize_name("Muhammad Zulqarnain")
        idf = {"muhammad": 0.15, "zulqarnain": 1.0}
        keys = name_block_keys(tokens, idf)
        assert keys & set(token_phonetic_keys("zulqarnain"))
        assert not (keys & set(token_phonetic_keys("muhammad")) - keys)

    def test_common_token_is_dropped_when_rarer_ones_exist(self):
        tokens = normalize_name("Muhammad Ali Zulqarnain")
        idf = {"muhammad": 0.15, "ali": 0.2, "zulqarnain": 1.0}
        keys = name_block_keys(tokens, idf)
        assert not (keys & set(token_phonetic_keys("muhammad")))

    def test_unknown_tokens_are_treated_as_distinctive(self):
        # Recall-safe direction: never drop a token we know nothing about.
        keys = name_block_keys(("zulqarnain",), {})
        assert keys == frozenset(token_phonetic_keys("zulqarnain"))

    def test_empty_name_yields_no_keys(self):
        assert name_block_keys((), {}) == frozenset()

    def test_is_deterministic_under_token_order(self):
        idf = {"ali": 0.2, "khan": 0.4, "zulqarnain": 1.0}
        forward = name_block_keys(("ali", "khan", "zulqarnain"), idf)
        backward = name_block_keys(("zulqarnain", "khan", "ali"), idf)
        assert forward == backward
