# Pet Database Test Cases

This document is aligned with the current SQLite implementation verified on April 23, 2026.

## Test Strategy

The project now uses two complementary validation tracks:

1. Automated regression tests in [tests/test_backend.py](tests/test_backend.py)
2. Manual demonstration-oriented checks for SQL, API, and workflow behavior

## Quick Run

Rebuild the database:

```powershell
python src\web_server.py --reset-db
```

Run automated tests:

```powershell
python -m unittest discover -s tests -v
```

## Automated Coverage

| Test class | Coverage |
|---|---|
| `InitializationTests` | database rebuild, index creation, clean high-severity audit |
| `ConstraintTests` | schema-level `CHECK` and `UNIQUE` enforcement |
| `QueryRegistryTests` | all official queries are read-only and executable in SQLite; LLM routing metadata |
| `WorkflowTests` | create application, approve application, create follow-up |
| `HttpSmokeTests` | frontend file serving, dashboard API, analytics API, review workflow API, LLM query API |

## Manual SQL Validation

The official SQL deliverables are the only SQL query artifacts that count for requirements 6 and 7:

- [src/queries/operational_queries.sql](src/queries/operational_queries.sql)
- [src/queries/analytical_queries.sql](src/queries/analytical_queries.sql)

Each query is SQLite-native and can be executed directly.

### Operational Queries

| Case ID | Query | What to verify | Snapshot on April 23, 2026 |
|---|---|---|---|
| `TC-OP-01` | `Q1 View all pets currently housed in a specific shelter` | returns one row per pet in shelter `1`; newest intake first | 10 rows |
| `TC-OP-02` | `Q2 View all pets that are currently available for adoption` | returns only `PET.status = 'available'` | 11 rows |
| `TC-OP-03` | `Q3 View the full health information of a specific pet` | unified timeline; no vaccination-medical Cartesian product | 2 rows for `pet_id = 5` |
| `TC-OP-04` | `Q4 View pets whose vaccination due date is approaching` | only records with non-null due dates inside the next 30 days from execution date | 20 rows on April 23, 2026 |
| `TC-OP-05` | `Q5 View upcoming care assignments for a volunteer` | one row per assignment for `volunteer_id = 2` | 1 row |
| `TC-OP-06` | `Q6 View all adoption applications that are currently under review` | only `status = 'Under Review'`; oldest first | 3 rows |

### Analytical Queries

| Case ID | Query | What to verify | Snapshot on April 23, 2026 |
|---|---|---|---|
| `TC-AN-01` | `Q1 Analyze current occupancy of each shelter` | includes all shelters and computes occupancy rate in SQLite | 3 rows |
| `TC-AN-02` | `Q2 Analyze pets that have stayed the longest in the shelter` | only available pets; `days_in_shelter` uses `julianday()` | 11 rows |
| `TC-AN-03` | `Q3 Analyze adoption application results by housing type` | one row per housing type with approval and rejection counts | 4 rows |
| `TC-AN-04` | `Q4 Analyze adoption demand and success rate by pet species` | one row per species with application volume and success rate | 4 rows |
| `TC-AN-05` | `Q5 Analyze volunteer workload based on care assignments` | includes volunteers with zero assignments | 10 rows |
| `TC-AN-06` | `Q6 Analyze post-adoption follow-up outcomes` | grouped by `FOLLOW_UP.result_status` | 4 rows |

### Representative Snapshot Rows

These rows were observed during verification on April 23, 2026:

```text
Analyze current occupancy of each shelter
  shelter_id=3, shelter_name=Animal Rescue Center, capacity=40, current_pet_count=5, occupancy_rate=12.5

Analyze pets that have stayed the longest in the shelter
  pet_id=1, name=Luna, species=Dog, breed=Labrador, intake_date=2025-04-27, days_in_shelter=360

Analyze adoption application results by housing type
  housing_type=Apartment, total_applications=4, approved_count=3, rejected_count=1, approval_rate=75.0

Analyze volunteer workload based on care assignments
  volunteer_id=4, full_name=Olivia Wright, total_assignments=2, completed_tasks=2

View all adoption applications that are currently under review
  application_id=8, applicant_name=Elizabeth Baker, pet_name=Nala, status=Under Review
```

## Manual Workflow Validation

### `TC-WF-01` Create a new application

Goal:

- create an adoption application for an available pet
- confirm the pet becomes reserved in the same workflow

How to verify:

1. Start `python src\web_server.py --reset-db`
2. Open `http://127.0.0.1:8000/pawtrack_demo.html`
3. Go to `Applications`
4. Click `+ New application`
5. Submit a valid application for an available pet

Expected result:

- a new `ADOPTION_APPLICATION` row is created with raw status `Under Review`
- the UI shows display label `Pending`
- the selected pet changes to raw status `reserved`

Automated counterpart:

- `WorkflowTests.test_create_approve_and_follow_up_workflow_stays_consistent`
- `HttpSmokeTests.test_frontend_and_core_api_paths_smoke`

### `TC-WF-02` Approve an application

Goal:

- review a pending application
- confirm that adoption record creation and pet-state transition happen transactionally

How to verify:

1. Open the `Applications` tab
2. Select a row labeled `Pending`
3. Click `Review`
4. Enter a decision note and approve the application

Expected result:

- application raw status becomes `Approved`
- a new `ADOPTION_RECORD` row is created
- the related pet raw status becomes `adopted`
- other under-review applications for the same pet are automatically closed

Automated counterpart:

- `WorkflowTests.test_create_approve_and_follow_up_workflow_stays_consistent`
- `HttpSmokeTests.test_frontend_and_core_api_paths_smoke`

### `TC-WF-03` Record a follow-up

Goal:

- create a follow-up only for an existing adoption

Expected result:

- new `FOLLOW_UP` row is inserted
- `result_status` is returned with both raw and display forms in the API payload

Automated counterpart:

- `WorkflowTests.test_create_approve_and_follow_up_workflow_stays_consistent`

### `TC-WF-04` Safe natural-language query

Goal:

- confirm that prompt routing uses the reviewed registry instead of arbitrary SQL generation

API example:

```http
POST /api/llm-query
Content-Type: application/json

{
  "prompt": "Which shelter is most occupied?"
}
```

Expected result:

- response includes `matchedQuery.name`, `title`, `category`, and `readOnly`
- `matchedQuery.readOnly` is `true`
- results come from one of the official SQL files

Automated counterpart:

- `QueryRegistryTests.test_llm_query_returns_read_only_metadata`
- `HttpSmokeTests.test_frontend_and_core_api_paths_smoke`

### `TC-WF-05` GLM prompt-to-SQL generation

Goal:

- confirm that GLM can generate an information-retrieval SQLite query only after backend validation
- confirm that unsafe generated SQL is rejected before execution

API example:

```http
POST /api/llm-generate-query
Content-Type: application/json

{
  "prompt": "Which shelter has the highest occupancy?",
  "promptMethod": "schema_grounded",
  "execute": true
}
```

Expected result:

- response includes `generatedSql`, `promptMethod`, `validation`, `rowCount`, and `rows`
- `validation.safe` is `true` for accepted SQL
- unsafe statements such as `DELETE`, `DROP`, multi-statement SQL, and `PRAGMA` return an error and are not executed

Automated counterpart:

- `QueryRegistryTests.test_glm_generated_query_executes_after_validation_with_fake_client`
- `QueryRegistryTests.test_glm_generated_query_rejects_unsafe_sql`
- `QueryRegistryTests.test_glm_generated_query_reports_non_json_output`
- `QueryRegistryTests.test_self_check_repair_uses_one_sqlite_error_guided_retry`
- `HttpSmokeTests.test_glm_generate_query_reports_missing_api_key_without_breaking_template_route`

## Constraint Validation

### `TC-CON-01` Invalid pet status is rejected

Action:

- attempt to insert `PET.status = 'flying'`

Expected result:

- SQLite raises `IntegrityError`

Automated counterpart:

- `ConstraintTests.test_invalid_pet_status_is_rejected_by_schema`

### `TC-CON-02` One application cannot create multiple adoption records

Action:

- attempt to insert a second `ADOPTION_RECORD` using an existing `application_id`

Expected result:

- SQLite raises `IntegrityError`

Automated counterpart:

- `ConstraintTests.test_duplicate_adoption_record_application_id_is_rejected_by_schema`

### `TC-CON-03` Indexes are actually created

Action:

- inspect `sqlite_master`

Expected result:

- runtime database contains the documented indexes from `src/schema/indexing.sql`

Automated counterpart:

- `InitializationTests.test_initialization_builds_indexes_and_clean_audit`

## Frontend Smoke Checklist

Use this checklist for demos:

- backend starts successfully after `--reset-db`
- `pawtrack_demo.html` loads through the backend
- dashboard cards render real data
- applications page can create and review an application
- analytics page renders occupancy and follow-up sections
- LLM Bonus page shows audit rows and a read-only query catalog
- safe natural-language query returns matched-query metadata

Automated counterpart:

- `HttpSmokeTests.test_frontend_and_core_api_paths_smoke`
