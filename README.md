# Pet Adoption Center Management System

SQLite-backed course project for managing shelters, pets, adoption applications, completed adoptions, follow-ups, medical history, vaccinations, and volunteer care assignments.

中文说明：本仓库已经统一到一套真实可运行的 SQLite 实现，文档、SQL、前后端和测试现在使用同一套业务口径。

## Delivery Summary

- ER design, table set, field set, and relationships were kept unchanged.
- The schema was hardened with declarative constraints that match the documented design.
- Official SQL deliverables now run directly on SQLite.
- The web prototype, LLM bonus page, and MCP server all use the same reviewed read-only query registry.
- Index recommendations are now applied during database initialization instead of remaining documentation-only.

## Repository Map

| Path | Purpose |
|---|---|
| `ER Design for the Pet Adoption Center Management System.md` | Design rationale, functional requirements, cardinalities, FDs, normalization |
| `mermaid-ER-diagram.png` | ER diagram artifact |
| `data/` | CSV seed data used to rebuild the database |
| `src/schema/table.sql` | Full schema definition with PK/FK/`CHECK`/`UNIQUE` constraints |
| `src/schema/indexing.sql` | Representative indexes tied to operational and analytical workloads |
| `src/queries/operational_queries.sql` | 6 operational read-only SQLite queries |
| `src/queries/analytical_queries.sql` | 6 analytical read-only SQLite queries |
| `src/WORKFLOW_SQL_EXAMPLES.md` | Workflow-oriented mutation examples kept outside the read-only registry |
| `src/query_registry.py` | Shared reviewed read-only query catalog and prompt routing |
| `src/llm_sql_assistant.py` | GLM prompt-to-SQL generation, prompt construction, SQL validation, and read-only execution |
| `src/llm_prompt_cases.json` | Prompt-to-SQL evaluation cases |
| `src/llm_prompt_eval.py` | Manual GLM prompt-method evaluation runner |
| `src/web_server.py` | Database initializer, audit logic, API layer, CRUD validation |
| `src/mcp_server.py` | Optional MCP server exposing the same read-only query registry |
| `pawtrack_demo.html` | Single-file frontend demo |
| `test_cases.md` | Manual test design and reproducible validation checklist |
| `REQUIREMENT_TRACEABILITY.md` | Requirement-to-evidence mapping for report and presentation use |
| `tests/test_backend.py` | Automated regression tests |

## Data Snapshot

Verified after rebuild on April 23, 2026:

| Table | Rows |
|---|---:|
| `SHELTER` | 3 |
| `PET` | 20 |
| `APPLICANT` | 15 |
| `ADOPTION_APPLICATION` | 15 |
| `ADOPTION_RECORD` | 6 |
| `FOLLOW_UP` | 16 |
| `MEDICAL_RECORD` | 25 |
| `VACCINATION` | 20 |
| `VOLUNTEER` | 10 |
| `CARE_ASSIGNMENT` | 15 |

Status snapshot on April 23, 2026:

- `PET.status`: `available=11`, `reserved=1`, `medical_hold=2`, `adopted=6`
- `ADOPTION_APPLICATION.status`: `Under Review=3`, `Approved=6`, `Rejected=6`
- `FOLLOW_UP.result_status`: `Excellent=2`, `Good=6`, `Satisfactory=2`, `Needs Improvement=6`

## Schema and Enforcement

The implementation preserves the original ER structure while making the documented rules executable:

- Foreign keys enforce entity relationships.
- `CHECK` constraints enforce controlled domains such as:
  - `PET.status`
  - `ADOPTION_APPLICATION.status`
  - `PET.species`
  - `PET.sex`
  - `MEDICAL_RECORD.record_type`
  - `CARE_ASSIGNMENT.shift`, `task_type`, `status`
  - `FOLLOW_UP.followup_type`, `result_status`
- Same-row temporal checks enforce:
  - pet birth date cannot be after intake date
  - application review date cannot be before application date
  - vaccination due date cannot be before vaccination date
- `ADOPTION_RECORD.application_id` is `UNIQUE`, matching the documented 1:0..1 relationship between application and adoption record.
- Cross-row and cross-table workflow rules remain application-enforced and are surfaced in the audit:
  - shelter capacity
  - pet workflow consistency
  - approved application uniqueness per pet
  - care-assignment shelter consistency
  - follow-up timing and adoption workflow ordering

The integrity audit exposed by `GET /api/llm-bonus` labels each rule by enforcement layer: `schema`, `application`, or audit-oriented review logic.

## Official SQL Deliverables

The official query set contains 12 reviewed read-only SQLite queries:

- Operational:
  - shelter pet roster
  - adoptable pets
  - pet health timeline
  - vaccination due list
  - volunteer schedule
  - under-review application queue
- Analytical:
  - shelter occupancy
  - long-stay pets
  - approval outcomes by housing type
  - adoption demand and success by species
  - volunteer workload
  - post-adoption follow-up outcomes

Important changes from the earlier draft:

- MySQL-only functions such as `CURDATE()`, `DATE_ADD()`, and `DATEDIFF()` were removed from the official deliverables.
- The pet-health query no longer creates a vaccination-medical Cartesian product; it now returns one unified event timeline.
- Mutation examples are no longer mixed into the query registry.

## Prototype and API

### Frontend

`pawtrack_demo.html` is a single-file prototype covering:

- Dashboard
- Pets
- Applications
- Medical
- Volunteers
- Analytics
- LLM Bonus

The UI uses backend-returned raw values for business logic and display labels for presentation. For example:

- application workflow raw value: `Under Review`
- application display label: `Pending`
- pet workflow raw value: `reserved`
- pet display label: `Reserved`

### Core endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Health check and active database path |
| `GET /api/dashboard` | Dashboard metrics, status overview, recent activity |
| `GET /api/analytics` | Analytical query outputs |
| `GET /api/llm-bonus` | Architecture refinement summary, audit, prompt patterns, query catalog |
| `POST /api/llm-query` | Natural-language routing to a reviewed read-only SQL query |
| `POST /api/llm-generate-query` | GLM prompt-to-SQL generation guarded by read-only validation |
| `GET /api/pets` | Pet roster with shelter data and status labels |
| `GET /api/applicants` | Applicant data |
| `GET /api/applications` | Adoption applications with raw/display status fields |
| `POST /api/applications` | Create a new application and reserve the pet |
| `PATCH /api/applications/{id}/review` | Approve or reject a pending application |
| `GET /api/adoption-records` | Completed adoption records |
| `GET /api/follow-ups` | Follow-up records |
| `POST /api/follow-ups` | Create a follow-up for a completed adoption |
| `GET /api/medical-records` | Medical history |
| `GET /api/vaccinations?upcoming=true` | Vaccination list or due-soon subset |
| `GET /api/volunteers` | Volunteer roster |
| `GET /api/care-assignments` | Care assignments |

Generic CRUD routes are also available for `shelters`, `pets`, `applicants`, `medical-records`, `vaccinations`, `volunteers`, `care-assignments`, and `follow-ups` through:

- `POST /api/{resource}`
- `PATCH /api/{resource}/{id}`
- `DELETE /api/{resource}/{id}`

## LLM + Database Bonus

This repository implements Option A in a controlled way.

### Part 1: LLM-assisted architecture review

`GET /api/llm-bonus` exposes:

- refined design notes
- enforcement-layer-aware integrity checks
- current audit findings with sample rows
- reviewed query catalog metadata

### Part 2: GLM prompt-to-SQL investigation

The project now contains two assistant paths:

- `POST /api/llm-query`: baseline safe routing into the reviewed SQL registry in `src/query_registry.py`
- `POST /api/llm-generate-query`: GLM-generated SQLite SQL with strict read-only validation before execution

The generated path supports four prompt methods:

- `zero_shot`
- `schema_grounded`
- `few_shot`
- `self_check_repair`

Generated SQL is accepted only if it is one `SELECT` or read-only `WITH ... SELECT` statement. The backend strips comments, rejects dangerous keywords, validates with `EXPLAIN QUERY PLAN`, executes through a read-only SQLite connection, installs a SQLite authorizer, and returns at most 50 rows.

Configure GLM access with environment variables:

```bash
export ZAI_API_KEY="your-rotated-key"
export GLM_MODEL="glm-5.1"
export GLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
```

The prompt evaluation pack lives in:

- `src/llm_prompt_cases.json`
- `src/llm_prompt_eval.py`
- `src/llm_prompt_results.json`

Run the evaluation manually after setting `ZAI_API_KEY`:

```bash
python3 src/llm_prompt_eval.py --methods zero_shot schema_grounded few_shot self_check_repair
```

## Optional MCP Server

The MCP server is optional. The core web system does not depend on it.

If you want MCP support:

```powershell
pip install -r requirements.txt
python src\mcp_server.py
```

Available tools:

- `list_available_queries`
- `execute_named_query`
- `natural_language_query`

These tools expose the same read-only registry used by `/api/llm-query`.

## How to Run

### Prerequisites

- Python 3.10+

### Rebuild and start the backend

```powershell
python src\web_server.py --reset-db
```

Normal startup:

```powershell
python src\web_server.py
```

Then open:

- `http://127.0.0.1:8000/pawtrack_demo.html`

## Verification

### Automated tests

```powershell
python -m unittest discover -s tests -v
```

### Syntax check

```powershell
python -m py_compile src\web_server.py src\mcp_server.py src\query_registry.py src\llm_sql_assistant.py src\llm_prompt_eval.py
```

### Manual checks

See:

- [test_cases.md](test_cases.md)
- [REQUIREMENT_TRACEABILITY.md](REQUIREMENT_TRACEABILITY.md)
- [src/LLM_DATABASE_BONUS.md](src/LLM_DATABASE_BONUS.md)

## Known Boundaries

- SQLite is the official target; the repository no longer treats MySQL syntax as the canonical deliverable.
- The prototype is designed for course demonstration and validation, not multi-user production deployment.
- The MCP server requires the optional `mcp` dependency, but the rest of the project does not.
- GLM-generated SQL requires `openai>=1.0` and `ZAI_API_KEY`; the reviewed-template assistant works without an API key.
