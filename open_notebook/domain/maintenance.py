"""Equipment-scoped maintenance retrieval (Smart Maintenance Guide).

Thin wrappers over the migration-27 SurrealQL functions
``fn::maintenance_vector_search`` / ``fn::maintenance_text_search``. Unlike
``text_search`` / ``vector_search`` (notebook scope or global), these restrict
retrieval to sources whose ``equipment_code`` metadata matches the requested
equipment code (case-insensitive, trimmed). Notes are intentionally excluded:
maintenance answers must be grounded in CMMS report sources only.
"""

from typing import List

from loguru import logger

from open_notebook.database.repository import repo_query
from open_notebook.exceptions import DatabaseOperationError, InvalidInputError


def normalize_equipment_code(code: str) -> str:
    """Trim user-supplied equipment codes; reject blank input loudly.

    A blank code would otherwise match nothing and return an empty result set
    indistinguishable from "no maintenance records". Matching itself is
    case-insensitive (SurrealQL uppercases both sides).
    """
    normalized = (code or "").strip()
    if not normalized:
        raise InvalidInputError("Equipment code must be provided")
    return normalized


async def maintenance_vector_search(
    keyword: str,
    equipment_code: str,
    results: int = 10,
    minimum_score: float = 0.2,
) -> List[dict]:
    """Vector search restricted to one equipment's CMMS sources."""
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    code = normalize_equipment_code(equipment_code)
    try:
        from open_notebook.utils.embedding import generate_embedding

        embed = await generate_embedding(keyword)
        search_results = await repo_query(
            """
            SELECT * FROM fn::maintenance_vector_search(
                $embed, $results, $minimum_score, $code);
            """,
            {
                "embed": embed,
                "results": results,
                "minimum_score": minimum_score,
                "code": code,
            },
        )
        return sorted(
            search_results or [],
            key=lambda item: (
                -float(item.get("similarity") or 0.0),
                str(item.get("id") or ""),
            ),
        )
    except InvalidInputError:
        raise
    except Exception as e:
        logger.error(f"Error performing maintenance vector search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def maintenance_text_search(
    keyword: str,
    equipment_code: str,
    results: int = 10,
) -> List[dict]:
    """BM25 text search restricted to one equipment's CMMS sources."""
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    code = normalize_equipment_code(equipment_code)
    try:
        search_results = await repo_query(
            """
            SELECT * FROM fn::maintenance_text_search($keyword, $results, $code);
            """,
            {
                "keyword": keyword,
                "results": results,
                "code": code,
            },
        )
        return search_results or []
    except InvalidInputError:
        raise
    except Exception as e:
        logger.error(f"Error performing maintenance text search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
