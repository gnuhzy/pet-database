# LLM + Database Bonus

This repository implements the LLM bonus in two controlled layers:

1. LLM-assisted review of database architecture and data integrity.
2. GLM prompt-to-SQL generation with strict read-only validation.

The implementation is exposed through:

- `GET /api/llm-bonus`
- `POST /api/llm-generate-query`

SQLite is the official execution target.

## Part 1: LLM-Assisted Architecture Review

### Goal

Use GLM as a database design-review assistant, not as an unrestricted SQL generator. The architecture review focuses on the first 5% bonus objective:

- integrity constraints
- workflow consistency
- anomaly detection
- efficient data access

### GLM Review Workflow

The original ER design, schema draft, seed-data domains, workflow rules, and representative SQL workloads were given to GLM with a review prompt asking for:

- weak integrity boundaries that should become SQLite constraints
- cross-table rules that cannot be expressed by a single SQLite `CHECK`
- anomaly records that should be detectable in repeatable audits
- indexes that should support daily management and analytical queries

The accepted refinements preserve the original entity set, relationships, primary keys, and foreign keys. GLM suggestions were applied only when they could be made executable in the SQLite implementation or verifiable through the audit API.

### Original vs Refined Design

The ER structure stayed the same, but the implementation was hardened.

| Area | Original design gap | GLM-assisted refined implementation |
|---|---|---|
| Controlled domains | Workflow states and dropdown values were plain text | `CHECK` constraints now enforce pet status, application status, pet species/sex, care assignment domains, medical record type, and follow-up domains |
| Cardinality hardening | The ER design implied one adoption record per application, but raw SQL could duplicate it | `ADOPTION_RECORD.application_id` is now `UNIQUE`, and approval logic checks existing approved applications |
| Temporal consistency | Date ordering rules were implicit or spread across workflows | Same-row date rules are SQLite `CHECK` constraints; cross-table timing is validated in application logic and audited |
| Workflow-derived state | Pet status, application review state, and adoption records could drift apart | application creation/review updates related rows transactionally |
| Anomaly detection | Foreign keys did not catch capacity overflow, orphaned workflow states, or duplicate active reviews | `GET /api/llm-bonus` runs executable audit checks with severity, enforcement layer, finding count, and sample rows |
| Efficient access paths | Index recommendations were documentation-only | `src/schema/indexing.sql` is executed during initialization and verified by tests |

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

The second 5% LLM bonus requirement asks for prompt methods that guide an LLM to generate accurate database queries. This repository now exposes one GLM-backed prompt-to-SQL path:

- `POST /api/llm-generate-query`: generates one SQLite information-retrieval query, validates it, and only then executes it.

The GLM-generated path is intentionally not an unrestricted SQL console. GLM proposes candidate SQL; the backend owns the safety decision.

### Prompt Methods

`src/llm_sql_assistant.py` implements four prompt methods:

- `zero_shot`: question + output contract + read-only rule.
- `schema_grounded`: live SQLite schema, keys, indexes, relationships, and domain values.
- `few_shot`: schema context plus compact hand-written safe SQLite examples.
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
export GLM_MAX_CONCURRENT_REQUESTS="1"
export GLM_MIN_REQUEST_INTERVAL_SECONDS="1"
export GLM_RATE_LIMIT_RETRIES="4"
export GLM_RATE_LIMIT_BACKOFF_SECONDS="2"
```

`GLM_API_KEY` is accepted as a compatibility fallback. The key is never stored in the repository.
The concurrency setting only controls local request fan-out. It cannot raise the GLM account quota; use a low value when the provider returns HTTP 429.

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

## Evidence

- GLM prompt-to-SQL core: [llm_sql_assistant.py](llm_sql_assistant.py)
- Prompt cases: [llm_prompt_cases.json](llm_prompt_cases.json)
- Prompt evaluation runner: [llm_prompt_eval.py](llm_prompt_eval.py)
- Web integration: [web_server.py](web_server.py)
- Query SQL: [operational_queries.sql](queries/operational_queries.sql), [analytical_queries.sql](queries/analytical_queries.sql)
- Workflow examples kept outside the read-only registry: [WORKFLOW_SQL_EXAMPLES.md](WORKFLOW_SQL_EXAMPLES.md)
- Automated verification: [tests/test_backend.py](../tests/test_backend.py)

## Verification Commands

```powershell
python src\web_server.py --reset-db
python -m unittest discover -s tests -v
python src\llm_prompt_eval.py --methods zero_shot schema_grounded few_shot self_check_repair
```
