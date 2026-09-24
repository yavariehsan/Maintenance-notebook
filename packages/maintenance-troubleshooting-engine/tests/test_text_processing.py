"""Persian/English text processing: normalization to lexical similarity."""

import pytest

from maintenance_troubleshooting.text import (
    AliasMap,
    CharacterNGramSimilarity,
    SimpleTokenizer,
    TextCanonicalizer,
    TextNormalizer,
    TokenSetSimilarity,
)


def test_arabic_chars_fold_to_persian() -> None:
    normalizer = TextNormalizer()
    # علي → علی, كابل → کابل, ة handling.
    assert normalizer.normalize("علي") == "علی"
    assert normalizer.normalize("كابل") == "کابل"


def test_diacritics_tatweel_and_digits() -> None:
    normalizer = TextNormalizer()
    assert normalizer.normalize("مـاشین") == "ماشین"
    assert normalizer.normalize("۰۱۲۳") == "0123"
    assert normalizer.normalize("٠١٢") == "012"
    assert normalizer.normalize("  دستگاه   روشن   ") == "دستگاه روشن"
    assert normalizer.normalize(None) == ""
    assert normalizer.normalize("   ") == ""


def test_tokenizer_keeps_technical_tokens() -> None:
    tokens = SimpleTokenizer().tokenize("تعویض بلبرینگ BR2 محور X-AXIS")
    assert "BR2" in [t.upper() for t in tokens]
    assert "br2" in tokens  # latin folded
    assert "بلبرینگ" in tokens
    assert SimpleTokenizer().tokenize("") == []


def test_canonicalizer_applies_configured_aliases() -> None:
    aliases = AliasMap(mapping={"انکودر": "encoder"})
    canonicalizer = TextCanonicalizer(aliases, SimpleTokenizer())
    assert canonicalizer.canonicalize("انکودر محور") == ["encoder", "محور"]
    assert canonicalizer.canonicalize_text("انکودر محور") == "encoder محور"
    assert aliases.canonicalize_token("نا آشنا") == "نا آشنا"
    extended = aliases.with_alias("کنتاکتور", "contactor")
    assert extended.canonicalize_token("کنتاکتور") == "contactor"
    assert "کنتاکتور" not in aliases.mapping  # with_alias copies


def test_token_set_similarity_is_jaccard() -> None:
    similarity = TokenSetSimilarity(SimpleTokenizer())
    assert similarity.similarity("a b c", "a b c") == pytest.approx(1.0)
    assert similarity.similarity("", "") == pytest.approx(1.0)
    assert similarity.similarity("a", "") == pytest.approx(0.0)
    assert similarity.similarity("a b", "b c") == pytest.approx(1 / 3)


def test_ngram_similarity_tolerates_typos() -> None:
    similarity = CharacterNGramSimilarity(n=3)
    assert similarity.name == "char-3gram-jaccard"
    close = similarity.similarity("بلبرینگ", "بلبرینک")
    far = similarity.similarity("بلبرینگ", "رینگ")
    assert 0.0 < far < close < 1.0
    with pytest.raises(ValueError):
        CharacterNGramSimilarity(n=0)
