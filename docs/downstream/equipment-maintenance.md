# Equipment import & Smart Maintenance Guide (downstream)

## Equipment model

Manual registration (`New Asset`) and Excel import share the same `asset`
record (migration 27). Excel → field mapping:

| Excel column           | Asset field      | Notes                          |
| ---------------------- | ---------------- | ------------------------------ |
| Code                   | `code`           | required, unique (see below)   |
| Main Description       | `name`           | required (existing rule)       |
| Factory                | `factory`        | new                            |
| Main Function Location | `location`       | reused                          |
| ZONE-Description       | `zone_description` | new                          |
| SITE-Description       | `site_description` | new                          |
| plant-description      | `plant_description` | new                         |
| Main Class             | `main_class`     | new                            |
| Sub Class              | `sub_class`      | new                            |
| Type-Description       | `asset_type`     | reused                          |
| Manufacture            | `manufacturer`   | reused                          |
| Model                  | `model`          | reused                          |

`description`, `status`, `serial_number` are manual-registration-only and
preserved untouched.

## Code semantics & duplicate policy

- `code` (e.g. `BR1`) is the first-class equipment identifier for the
  maintenance workflow. Matching is case-insensitive on the trimmed value.
- Uniqueness is enforced in the API/service layer with a `UNIQUE` index
  backstop (migration 27). Duplicates return 400 naming the conflict.
- Excel import never overwrites: in-file duplicates keep the first
  occurrence; codes already in the database are rejected. Every rejection is
  reported per row (1-based Excel row number + reason).
- Two-step import: `POST /api/assets/import?dry_run=true` previews
  (row counts, valid rows, issues); re-upload with `dry_run=false` persists
  valid rows only. Validation re-runs at persist time against current DB state.

## CMMS association

A CMMS report is a regular source with `equipment_code` metadata
(`PUT /sources/{id} {"equipment_code": "BR1"}`; empty string clears it).
No document duplication, no parallel store. Set the association **after**
source processing completes: the ingestion graph saves a stale source object
that would otherwise overwrite a concurrent edit (same read-modify-write
pattern as title/topics).

## Smart Maintenance Guide (`/maintenance-guide`, Processing section)

`POST /api/maintenance/ask {equipment_code, question}`:

1. resolves the equipment (404 when unknown; 400 on blank code/question),
2. lists its CMMS sources (`no_sources` when none),
3. retrieves chunks **only** through `fn::maintenance_vector_search` /
   `fn::maintenance_text_search` (migration 27), which constrain
   `source_embedding` / `source_insight` rows to sources carrying the
   requested code — enforced in SurrealQL, not just mentioned in the prompt,
4. synthesizes with the existing Ask prompts (`ask/query_process`,
   `ask/final_answer`, incl. `[document_id]` citations),
5. returns `no_context` instead of an invented answer when nothing relevant
   is retrieved.

Vector retrieval requires a configured embedding model; without one the
endpoint surfaces 422/500 rather than answering from a degraded context.
