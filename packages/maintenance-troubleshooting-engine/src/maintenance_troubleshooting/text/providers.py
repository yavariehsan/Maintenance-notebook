"""Optional embedding-provider boundary.

The core package never imports an embedding SDK. Concrete providers
(sentence-transformers, local models, hosted APIs) implement this protocol
in optional downstream modules; the core only depends on the interface.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Embed a batch of texts into fixed-width vectors."""

    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in input order."""
        ...
