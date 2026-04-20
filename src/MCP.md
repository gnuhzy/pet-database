# Pet Database MCP Server

## Overview

An MCP server that exposes pre-defined SQL queries from `src/queries/` as callable tools, enabling an external LLM to query the pet adoption center database using natural language.

Only queries defined in `src/queries/` can be executed — no arbitrary SQL is allowed.

## Running the Server

```bash
python3 src/mcp_server.py
```

The server communicates over stdio (stdin/stdout) and is compatible with any MCP client (Claude Desktop, etc.).

## MCP Tools

### `list_available_queries`
Returns all 14 available queries with names and descriptions, grouped by category (operational / analytical).

### `execute_named_query`
Executes a specific pre-defined query by name.
```json
{"query_name": "view_all_pets_that_are_currently_available_for_adoption"}
```

### `natural_language_query`
Given a natural language prompt, selects the best matching pre-defined query and executes it.
```json
{"nl_prompt": "show me pets in shelter 1"}
```

## Query Categories

**Operational (8 queries):** shelter pet views, adoptable pets, pet health info, vaccination alerts, volunteer assignments, adoption application review/approval, follow-up recording.

**Analytical (6 queries):** shelter occupancy, long-stay pets, approval rates by housing type, adoption success by species, volunteer workload, follow-up outcomes.

## Database

SQLite at `pet_database.db` (MySQL syntax normalized at runtime).

## Adding New Queries

1. Add a new query block to `src/queries/operational_queries.sql` or `src/queries/analytical_queries.sql`
2. Use the format:
   ```sql
   -- QN: Query Title
   -- Purpose: One-line description
   SELECT ...;
   ```
3. Restart the MCP server — queries are loaded dynamically.
