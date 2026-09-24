"""Text-processing abstractions: normalization to embeddings."""

from maintenance_troubleshooting.text.canonicalization import (
    AliasMap,
    TextCanonicalizer,
)
from maintenance_troubleshooting.text.normalization import (
    TextNormalizationOptions,
    TextNormalizer,
)
from maintenance_troubleshooting.text.providers import EmbeddingProvider
from maintenance_troubleshooting.text.similarity import (
    CharacterNGramSimilarity,
    TextSimilarity,
    TokenSetSimilarity,
)
from maintenance_troubleshooting.text.tokenization import (
    SimpleTokenizer,
    Tokenizer,
)

__all__ = [
    "AliasMap",
    "CharacterNGramSimilarity",
    "EmbeddingProvider",
    "SimpleTokenizer",
    "TextCanonicalizer",
    "TextNormalizationOptions",
    "TextNormalizer",
    "TextSimilarity",
    "TokenSetSimilarity",
    "Tokenizer",
]
