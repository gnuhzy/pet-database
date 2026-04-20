# Pet Database MCP Server

## Overview

An MCP server that exposes pre-defined SQL queries from `src/queries/` as callable tools, enabling an external LLM to query the pet adoption center database using natural language. Only queries defined in `src/queries/` can be executed — no arbitrary SQL is allowed.

## Architecture

```
External LLM → MCP Server → SQLite DB (pet_database.db)
                      ↑
            src/queries/*.sql (allowed queries)
```

The server acts as a safe interface: all SQL is pre-approved and parameterized. Natural language prompts are matched against a keyword map to select the appropriate query, and parameters are extracted from the prompt automatically.

## Running the Server

```bash
python3 src/mcp_server.py
```

The server communicates over stdio (stdin/stdout) and is compatible with any MCP client (Claude Desktop, etc.).

## MCP Tools

### `list_available_queries`
Returns all 14 available queries with names, descriptions, and parameter info grouped by category (operational / analytical). No arguments required.

### `execute_named_query`
Executes a specific pre-defined query by name, with optional parameters.

```json
{
  "query_name": "view_all_pets_currently_housed_in_a_specific_shelter",
  "params": {
    "shelter_id": 2
  }
}
```

If `params` is omitted, default values are used where applicable.

### `natural_language_query`
Given a natural language prompt, selects the best matching query, extracts parameter values from the prompt, and executes it.

```json
{
  "nl_prompt": "show me pets in shelter 3"
}
```

Parameter values are auto-extracted from the prompt (e.g., "shelter 3" → `shelter_id=3`, "14 days" → `days_ahead=14`). Write queries (INSERT/UPDATE) that require parameters not found in the prompt are rejected with a message directing the caller to use `execute_named_query` with explicit params.

## Query Parameters

Most operational queries accept parameters. Unknown parameter keys are rejected.

| Query | Parameters |
|-------|-----------|
| `view_all_pets_currently_housed_in_a_specific_shelter` | `shelter_id` (int) |
| `view_the_full_health_information_of_a_specific_pet` | `pet_id` (int) |
| `view_pets_whose_vaccination_due_date_is_approaching` | `days_ahead` (int, default 30) |
| `view_upcoming_care_assignments_for_a_volunteer` | `volunteer_id` (int) |
| `approve_a_selected_adoption_application` | `application_id` (int), `reviewer_name` (string), `decision_note` (string) |
| `insert_a_follow-up_record_after_a_completed_adoption` | `adoption_id` (int), `followup_type` (string), `pet_condition` (string), `adopter_feedback` (string), `result_status` (string), `staff_note` (string) |

Analytical queries and remaining operational queries (Q2, Q6) take no parameters.

## Query Categories

**Operational (8 queries):** shelter pet views, adoptable pets, pet health info, vaccination alerts, volunteer assignments, adoption application review/approval, follow-up recording.

**Analytical (6 queries):** shelter occupancy, long-stay pets, approval rates by housing type, adoption success by species, volunteer workload, follow-up outcomes.

## Database

SQLite at `pet_database.db` in the project root. MySQL-specific SQL functions (`CURDATE()`, `DATE_ADD()`, `DATEDIFF()`) are normalized to SQLite equivalents at runtime.

## Adding New Queries

1. Add a new query block to `src/queries/operational_queries.sql` or `src/queries/analytical_queries.sql`
2. Use the format:
   ```sql
   -- QN: Query Title
   -- Purpose: One-line description
   -- Params: param_name:type:description
   SELECT ... WHERE col = :param_name;
   ```
   - `Params:` is optional — omit it for queries that take no parameters
   - For multiple parameters, separate with commas: `-- Params: id:int:An ID, name:string:A name`
   - For INSERT/UPDATE/DELETE queries, the server automatically returns rows affected
3. Restart the MCP server — queries are loaded dynamically from all `.sql` files in `src/queries/`

## Parameter Format in SQL Files

Named parameters use `:name` syntax, compatible with both the SQL and the server's binding system:

```sql
-- Params: shelter_id:int:A shelter ID, days_ahead:int:Days ahead (default 30)
SELECT ... WHERE shelter_id = :shelter_id AND due_date <= DATE_ADD(CURDATE(), INTERVAL :days_ahead DAY);
```

Type annotations (`int` / `string`) are used for documentation and future validation.
