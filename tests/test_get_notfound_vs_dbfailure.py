"""ObjectModel.get(): missing record vs database failure (P0.5).

Genuinely missing rows raise NotFoundError (fail-fast/404 semantics
downstream). Infrastructure failures (connection refused, timeouts) must
surface as DatabaseOperationError — retryable in workers, 500 (never a
misleading 404) in the API. The previous blanket `except Exception ->
NotFoundError` conflated the two: an outage looked like mass deletion.
"""

from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.notebook import Source
from open_notebook.exceptions import (
    DatabaseOperationError,
    InvalidInputError,
    NotFoundError,
)


class TestGetDistinguishesMissingFromDbFailure:
    pytestmark = pytest.mark.asyncio

    async def test_missing_row_raises_not_found(self):
        with patch(
            "open_notebook.domain.base.repo_query",
            new=AsyncMock(return_value=[]),
        ):
            with pytest.raises(NotFoundError):
                await Source.get("source:gone")

    @pytest.mark.parametrize(
        "failure",
        [
            ConnectionError("refused"),
            TimeoutError("timed out"),
            RuntimeError("surrealdb transaction conflict"),
        ],
    )
    async def test_database_failure_is_not_not_found(self, failure):
        with patch(
            "open_notebook.domain.base.repo_query",
            new=AsyncMock(side_effect=failure),
        ):
            with pytest.raises(DatabaseOperationError):
                await Source.get("source:abc")

    async def test_blank_id_still_invalid_input(self):
        with pytest.raises(InvalidInputError):
            await Source.get("")
