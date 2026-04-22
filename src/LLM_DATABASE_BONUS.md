# LLM + Database Bonus

This repository implements the LLM bonus in two controlled layers:

1. LLM-assisted review of database architecture and data integrity.
2. Safe natural-language access to a reviewed read-only SQL registry.

The implementation is exposed through:

- `GET /api/llm-bonus`
- `POST /api/llm-query`
- optional MCP tools in `src/mcp_server.py`

SQLite is the official execution target.

## Part 1: LLM-Assisted Architecture Review

### Goal

Use the LLM as a design-review assistant, not as an unrestricted SQL generator. The review focuses on:

- integrity constraints
- workflow consistency
- anomaly detection
- access-path selection
- safe query exposure

### What Changed

The ER structure stayed the same, but the implementation was hardened.

| Area | Original gap | Refined implementation |
|---|---|---|
| Status domains | Free-text workflow fields could drift | Schema `CHECK` constraints now enforce the documented domains where appropriate |
| Adoption uniqueness | One application could create multiple adoption records in raw SQL | `ADOPTION_RECORD.application_id` is now `UNIQUE` |
| Temporal ordering | Some date relationships were only implicit | Same-row rules are enforced in schema; cross-table rules are audited and validated in application logic |
| Indexes | Indexes were documented but not guaranteed to exist at runtime | `src/schema/indexing.sql` now runs during initialization |
| Query safety | Query catalogs could include write statements | Shared registry now loads only reviewed read-only SQL from `*_queries.sql` |

### Enforcement Layers

The bonus page now reports each rule with an `enforcementLayer`:

- `schema`: enforced directly by SQLite constraints
- `application`: enforced by backend validation and transactional workflow logic
- audit-oriented review logic: surfaced as repeatable checks for drift detection

Representative schema-enforced rules:

```sql
CHECK (status IN ('available', 'reserved', 'adopted', 'medical_hold'))
```

```sql
CHECK (status IN ('Under Review', 'Approved', 'Rejected'))
```

```sql
UNIQUE (application_id)
```

Representative application-enforced rules:

- shelter capacity cannot be exceeded by active pets
- a reserved pet must have an active under-review application
- only one application can end as approved for a pet
- care assignments cannot cross shelter boundaries
- follow-up records cannot predate the adoption event they depend on

### Integrity Audit

`GET /api/llm-bonus` returns a repeatable audit pack containing:

- check id and title
- severity
- enforcement layer
- rationale
- refinement note
- executable SQL
- finding count
- sample rows

Examples of audited rules:

- invalid `PET.status`
- invalid `ADOPTION_APPLICATION.status`
- structured domain drift in care assignments, follow-up records, and medical records
- invalid applicant housing type
- malformed email format
- shelter capacity overflow
- cross-table temporal anomalies
- reserved pets without under-review applications
- approved applications without adoption records
- duplicate active applicant-pet reviews

## Part 2: GLM Prompt-to-SQL Investigation

### Design Principle

The second 5% LLM bonus requirement asks for prompt methods that guide an LLM to generate accurate database queries. This repository now implements that investigation in two complementary paths:

- `POST /api/llm-query`: a conservative baseline that routes a natural-language question to the reviewed read-only SQL registry.
- `POST /api/llm-generate-query`: a GLM-backed prompt-to-SQL path that generates one SQLite information-retrieval query, validates it, and only then executes it.

The GLM-generated path is intentionally not an unrestricted SQL console. GLM proposes candidate SQL; the backend owns the safety decision.

### Prompt Methods

`src/llm_sql_assistant.py` implements four prompt methods:

- `zero_shot`: question + output contract + read-only rule.
- `schema_grounded`: live SQLite schema, keys, indexes, relationships, and domain values.
- `few_shot`: schema context plus reviewed SQL examples from `src/queries`.
- `self_check_repair`: schema and examples plus a model self-check; if SQLite rejects the first safe draft, one error-guided repair attempt is allowed.

The schema context is generated from the running SQLite database using `sqlite_master`, `PRAGMA table_info`, `PRAGMA foreign_key_list`, and `PRAGMA index_list`, so the prompt stays aligned with the real schema.

### GLM API Contract

`POST /api/llm-generate-query`

Request:

```json
{
  "prompt": "Which shelter has the highest occupancy?",
  "promptMethod": "schema_grounded",
  "execute": true
}
```

Response shape:

```json
{
  "provider": "zhipu-glm",
  "model": "glm-5.1",
  "promptMethod": "schema_grounded",
  "generatedSql": "SELECT ...",
  "explanation": "The query counts active pets by shelter and sorts by occupancy.",
  "assumptions": [],
  "validation": {
    "safe": true,
    "readOnly": true
  },
  "rowCount": 3,
  "rows": [],
  "repairAttempts": 0
}
```

Environment configuration:

```bash
export ZAI_API_KEY="your-rotated-key"
export GLM_MODEL="glm-5.1"
export GLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
```

`GLM_API_KEY` is accepted as a compatibility fallback. The key is never stored in the repository.

### Safety Gate

Generated SQL must pass all backend checks before execution:

- comments are stripped before validation
- exactly one statement is allowed
- only `SELECT` or read-only `WITH ... SELECT` may run
- write, DDL, administrative, and attachment commands are blocked
- SQLite validates the plan through `EXPLAIN QUERY PLAN`
- execution uses a read-only database URI
- a SQLite authorizer denies non-read actions
- a progress handler prevents runaway queries
- returned rows are capped at 50

### Prompt Evaluation Pack

The prompt investigation is reproducible through:

- `llm_prompt_cases.json`: 20 prompts covering operational, analytical, filtered, aggregate, ambiguous, and unsafe requests
- `llm_prompt_eval.py`: manual GLM evaluation runner
- `llm_prompt_results.json`: generated results consumed by `GET /api/llm-bonus`

Run:

```bash
python3 src/llm_prompt_eval.py --methods zero_shot schema_grounded few_shot self_check_repair
```

### Baseline Safe Routing

The existing registry path remains available through `POST /api/llm-query` and the MCP server. It uses the same reviewed read-only SQL catalog as before and is useful as a safety baseline against the generated path.

Request:

```json
{
  "prompt": "Which shelter is most occupied?"
}
```

Response shape:

```json
{
  "prompt": "Which shelter is most occupied?",
  "safetyModel": "Prompt is routed to the shared reviewed read-only query registry; arbitrary SQL generation is disabled.",
  "matchedQuery": {
    "name": "analyze_current_occupancy_of_each_shelter",
    "title": "Analyze current occupancy of each shelter",
    "description": "Managers monitor how full each shelter is and identify capacity pressure.",
    "category": "analytical",
    "readOnly": true,
    "sql": "SELECT ..."
  },
  "rowCount": 3,
  "rows": [
    {
      "shelter_id": 3,
      "shelter_name": "Animal Rescue Center",
      "capacity": 40,
      "current_pet_count": 5,
      "occupancy_rate": 12.5
    }
  ]
}
```

### MCP Alignment

The optional MCP server now uses the exact same registry and exposes only:

- `list_available_queries`
- `execute_named_query`
- `natural_language_query`

This means the web path and the MCP path share the same safety boundary:

- same query source
- same read-only restriction
- same prompt-routing behavior

## Evidence

- Query registry: [query_registry.py](query_registry.py)
- GLM prompt-to-SQL core: [llm_sql_assistant.py](llm_sql_assistant.py)
- Prompt cases: [llm_prompt_cases.json](llm_prompt_cases.json)
- Prompt evaluation runner: [llm_prompt_eval.py](llm_prompt_eval.py)
- Web integration: [web_server.py](web_server.py)
- MCP integration: [mcp_server.py](mcp_server.py)
- Query SQL: [operational_queries.sql](queries/operational_queries.sql), [analytical_queries.sql](queries/analytical_queries.sql)
- Workflow examples kept outside the read-only registry: [WORKFLOW_SQL_EXAMPLES.md](WORKFLOW_SQL_EXAMPLES.md)
- Automated verification: [tests/test_backend.py](../tests/test_backend.py)

## Verification Commands

```powershell
python src\web_server.py --reset-db
python -m unittest discover -s tests -v
python src\llm_prompt_eval.py --methods zero_shot schema_grounded few_shot self_check_repair
```
