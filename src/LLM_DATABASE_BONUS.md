# LLM + Database Bonus

## Goal

This bonus component uses an LLM-assisted database workflow in two ways:

1. Refine the database architecture by reviewing integrity constraints, anomaly checks, and access paths.
2. Support natural-language information extraction through a safe query-routing layer.

The implementation is exposed in the web app under **LLM Bonus** and through these backend endpoints:

- `GET /api/llm-bonus`
- `POST /api/llm-query`
- MCP tools in `src/mcp_server.py`

---

## Part 1: LLM-Assisted Database Architecture Refinement

### Original Design

The original schema already contained normalized core entities:

- `SHELTER`
- `PET`
- `APPLICANT`
- `ADOPTION_APPLICATION`
- `ADOPTION_RECORD`
- `FOLLOW_UP`
- `MEDICAL_RECORD`
- `VACCINATION`
- `VOLUNTEER`
- `CARE_ASSIGNMENT`

The initial design used primary keys and foreign keys to preserve referential integrity. However, several business rules were still implicit:

- Status fields were stored as plain text.
- Pet availability and application workflow state could drift apart.
- Shelter capacity was a business rule but not automatically audited.
- Index choices were not tied directly to daily and analytical query workloads.
- Natural-language querying could be unsafe if arbitrary generated SQL were executed.

### LLM-Refined Design

The LLM-assisted review identified the following refinements:

| Area | Original design | LLM-assisted refinement | Implementation |
|------|-----------------|--------------------------|----------------|
| Status domains | Status columns were plain `VARCHAR` fields | Treat status values as controlled domains | Backend validation plus suggested `CHECK` constraints |
| Workflow integrity | Application and pet status could be updated independently | Reserve pets when applications are created; release pets after rejection if no pending application remains | Implemented in `POST /api/applications` and `PATCH /api/applications/{id}/review` |
| Anomaly detection | Foreign keys catch missing parent rows, but not business anomalies | Add repeatable audit checks | Implemented in `GET /api/llm-bonus` |
| Efficient access | Queries existed, but access paths were not tied to workloads | Index FK, status, and due-date fields | Documented in `src/schema/indexing.sql` |
| LLM query safety | Free-form SQL generation could hallucinate or mutate data | Route prompts to reviewed query templates | Implemented in MCP tools and `POST /api/llm-query` |

### Suggested Refined Constraints

Representative refinements suggested by the LLM review:

```sql
CHECK (status IN ('available', 'reserved', 'adopted', 'medical_hold'))
```

```sql
CHECK (status IN ('Under Review', 'Approved', 'Rejected'))
```

```sql
CREATE INDEX idx_application_status
ON ADOPTION_APPLICATION(status);
```

```sql
CREATE INDEX idx_vaccination_next_due
ON VACCINATION(next_due_date);
```

### Anomaly Detection

The backend now runs business-level checks, including:

- invalid `PET.status` values
- invalid `ADOPTION_APPLICATION.status` values
- shelter capacity overflow
- reserved pets without pending applications
- pending applications whose pets are not reserved
- adoption records linked to non-approved applications
- duplicate pending applications for the same applicant and pet

These are returned by:

```http
GET /api/llm-bonus
```

The frontend displays the check status, finding count, rationale, and recommended refinement.

---

## Part 2: Prompt Engineering for Database Querying

### Risk of Direct SQL Generation

Allowing an LLM to generate and execute arbitrary SQL is risky because it may:

- hallucinate table or column names,
- generate SQL that does not match the schema,
- perform unintended updates or deletes,
- expose SQL injection risks if user text is inserted into SQL directly.

### Refined Prompt-to-Query Method

Instead of executing arbitrary LLM-generated SQL, the system uses a safe query registry:

1. Staff asks a natural-language question.
2. The backend extracts intent using keyword and description matching.
3. The prompt is mapped to a reviewed SQL query from `src/queries`.
4. The web assistant executes only read-only `SELECT` queries.
5. The MCP server exposes the same query registry to external LLM clients.

### Example Prompt Patterns

| Prompt pattern | Example prompt | Matched query |
|----------------|----------------|---------------|
| Intent-first | Show pets whose vaccination is due soon | vaccination due-date query |
| Schema-grounded | Analyze adoption approval rate by applicant housing type | housing approval analytical query |
| Metric-oriented | Which volunteers completed the most care tasks? | volunteer workload query |
| Read-only extraction | List available pets for adoption | available pets query |

### Implemented Interfaces

Backend endpoint:

```http
POST /api/llm-query
Content-Type: application/json

{
  "prompt": "Which shelter is most occupied?"
}
```

MCP tools:

- `list_available_queries`
- `execute_named_query`
- `natural_language_query`

The LLM Bonus frontend page demonstrates this method interactively.
