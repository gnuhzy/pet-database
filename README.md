# Pet Adoption Center Management System

SQLite-backed course project for managing shelters, pets, adoption applications, completed adoptions, follow-ups, medical history, vaccinations, and volunteer care assignments.

中文说明：本仓库已经统一到一套真实可运行的 SQLite 实现，文档、SQL、前后端和测试现在使用同一套业务口径。

## Delivery Summary

- ER design, table set, field set, and relationships were kept unchanged.
- The schema was hardened with declarative constraints that match the documented design.
- Official SQL deliverables now run directly on SQLite.
- The web prototype uses GLM-generated prompt-to-SQL with backend read-only validation.
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
| `src/query_registry.py` | Parser/catalog helper for the 12 official reviewed read-only SQL deliverables |
| `src/llm_sql_assistant.py` | GLM prompt-to-SQL generation, prompt construction, SQL validation, and read-only execution |
| `src/llm_prompt_cases.json` | Prompt-to-SQL evaluation cases |
| `src/llm_prompt_eval.py` | Manual GLM prompt-method evaluation runner |
| `src/web_server.py` | Database initializer, audit logic, API layer, CRUD validation |
| `src/mcp_server.py` | Optional MCP server exposing named read-only query tools |
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
- Assistant

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
| `GET /api/llm-bonus` | Architecture refinement summary, audit, prompt methods, evaluation metadata |
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

- original-vs-refined database design comparison
- GLM-assisted integrity and access-path refinements
- enforcement-layer-aware integrity checks
- current audit findings with sample rows
- GLM prompt-method and evaluation metadata

The accepted architecture refinements preserve the original ER entity set and relationships while making key rules executable: controlled domains, adoption-record uniqueness, temporal ordering, workflow-derived pet/application/adoption state, anomaly audits, and runtime indexes.

This evidence is documented for the report and remains available through the API; it is not shown as a separate frontend page.

### Part 2: GLM prompt-to-SQL investigation

The project exposes one assistant path:

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
export GLM_MAX_CONCURRENT_REQUESTS="1"
export GLM_MIN_REQUEST_INTERVAL_SECONDS="1"
export GLM_RATE_LIMIT_RETRIES="4"
export GLM_RATE_LIMIT_BACKOFF_SECONDS="2"
```

`GLM_MAX_CONCURRENT_REQUESTS` is a local throttle, not a provider quota override. Keep it low if GLM returns HTTP 429; raise it only after the account quota is upgraded.

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

## How to Run

### Prerequisites

- Python 3.10+
- Run commands from the project root: `pet-database/`

### Demo Quick Start (recommended)

1) (Optional, first run only) install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2) (Optional) rebuild database from CSV seed data:

```bash
python3 src/web_server.py --reset-db
```

3) Start the server in the foreground and keep this terminal open:

```bash
python3 src/web_server.py --host 127.0.0.1 --port 8000
```

You should see:

```text
PawTrack API running at http://127.0.0.1:8000
Open http://127.0.0.1:8000/pawtrack_demo.html
```

Then open:

- `http://127.0.0.1:8000/pawtrack_demo.html`

4) Health check (in another terminal):

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expected: JSON containing `"ok": true`.

### If you see "127.0.0.1 refused to connect"

Run:

```bash
lsof -iTCP:8000 -sTCP:LISTEN -n -P
```

- If there is no output: the server is not running. Start it again with:

```bash
python3 src/web_server.py --host 127.0.0.1 --port 8000
```

- If port `8000` is occupied by another process, stop it and retry:

```bash
PID=$(lsof -tiTCP:8000 -sTCP:LISTEN -n -P)
kill "$PID"
python3 src/web_server.py --host 127.0.0.1 --port 8000
```

## Verification

### Automated tests

```bash
python3 -m unittest discover -s tests -v
```

### Syntax check

```bash
python3 -m py_compile src/web_server.py src/mcp_server.py src/query_registry.py src/llm_sql_assistant.py src/llm_prompt_eval.py
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
- GLM-generated SQL requires `openai>=1.0` and `ZAI_API_KEY`.
