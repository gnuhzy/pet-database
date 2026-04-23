# Pet Database MCP Server

## Overview

`src/mcp_server.py` is an optional MCP server that exposes the reviewed read-only SQL deliverables as named tools.

It does not execute arbitrary SQL.

Safety model:

- query source: `src/query_registry.py`
- official SQL source files: `src/queries/operational_queries.sql` and `src/queries/analytical_queries.sql`
- exposed query type: reviewed read-only `SELECT` only

SQLite is the official execution target.

## Prerequisites

The MCP server is optional. Install its dependency only if you want MCP integration:

```powershell
pip install -r requirements.txt
```

You also need the SQLite database file to exist. The simplest way to create it is:

```powershell
python src\web_server.py --reset-db
```

## Running the Server

```powershell
python src\mcp_server.py
```

The server communicates over stdio and can be connected by MCP-compatible clients.

## Available Tools

### `list_available_queries`

Lists every reviewed read-only query currently available through the shared registry.

### `execute_named_query`

Executes one reviewed read-only query by exact name.

Example input:

```json
{
  "query_name": "view_all_pets_that_are_currently_available_for_adoption"
}
```

## Current Catalog

As of April 23, 2026, the registry exposes 12 reviewed read-only queries:

- Operational:
  - `view_all_pets_currently_housed_in_a_specific_shelter`
  - `view_all_pets_that_are_currently_available_for_adoption`
  - `view_the_full_health_information_of_a_specific_pet`
  - `view_pets_whose_vaccination_due_date_is_approaching`
  - `view_upcoming_care_assignments_for_a_volunteer`
  - `view_all_adoption_applications_that_are_currently_under_review`
- Analytical:
  - `analyze_current_occupancy_of_each_shelter`
  - `analyze_pets_that_have_stayed_the_longest_in_the_shelter`
  - `analyze_adoption_application_results_by_housing_type`
  - `analyze_adoption_demand_and_success_rate_by_pet_species`
  - `analyze_volunteer_workload_based_on_care_assignments`
  - `analyze_post-adoption_follow-up_outcomes`

## Output Shape

Query results include explicit metadata:

- query name
- title
- category
- `read_only: true`
- row count
- formatted result table

This makes the safety boundary visible during demos.

## Adding or Updating Queries

1. Edit either:
   - `src/queries/operational_queries.sql`
   - `src/queries/analytical_queries.sql`
2. Use the required block format:

```sql
-- QN: Query Title
-- Purpose: One-line description
-- Example: Optional execution note
-- Result characteristics: Optional result note
SELECT ...;
```

3. Keep the query read-only.
4. Restart the MCP server.
5. Re-run:

```powershell
python -m unittest discover -s tests -v
```

## Non-Goals

The MCP server intentionally does not expose:

- `INSERT`
- `UPDATE`
- `DELETE`
- arbitrary SQL execution
- natural-language prompt routing to fixed SQL templates
- workflow mutations such as approval or follow-up creation

Those write-side examples are documented separately in [WORKFLOW_SQL_EXAMPLES.md](WORKFLOW_SQL_EXAMPLES.md).
