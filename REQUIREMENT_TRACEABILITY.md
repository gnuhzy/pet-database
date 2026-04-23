# Requirement Traceability and Evidence Pack

Verified against the repository state on April 23, 2026. SQLite is the official execution target for this project.

## Evidence Matrix

| PDF item | What the requirement asks for | Primary repository evidence | Runtime / test evidence |
|---|---|---|---|
| Requirement 1 | Problem background, scope, and functional requirements | [README.md](README.md), [ER Design for the Pet Adoption Center Management System.md](ER%20Design%20for%20the%20Pet%20Adoption%20Center%20Management%20System.md) | `python -m unittest discover -s tests -v` |
| Requirement 2 | ER modeling of entities, attributes, relationships, and cardinalities | [ER Design for the Pet Adoption Center Management System.md](ER%20Design%20for%20the%20Pet%20Adoption%20Center%20Management%20System.md) | Design is reflected in [src/schema/table.sql](src/schema/table.sql) without changing table or relationship structure |
| Requirement 3 | ER diagram | [mermaid-ER-diagram.png](mermaid-ER-diagram.png), [src/diagrams/mermaid-ER-diagram.png](src/diagrams/mermaid-ER-diagram.png) | Visual artifact included in repo |
| Requirement 4 | Relational schema, keys, functional dependencies, and normalization | [src/schema/table.sql](src/schema/table.sql), [ER Design for the Pet Adoption Center Management System.md](ER%20Design%20for%20the%20Pet%20Adoption%20Center%20Management%20System.md) | `tests/test_backend.py::InitializationTests`, `tests/test_backend.py::ConstraintTests` |
| Requirement 5 | Sample data that supports realistic workflows | [data](data), [README.md](README.md) | Database rebuild from CSV is exercised in every automated test case |
| Requirement 6 | Operational SQL queries | [src/queries/operational_queries.sql](src/queries/operational_queries.sql) | `tests/test_backend.py::QueryRegistryTests.test_official_queries_are_read_only_and_runnable_in_sqlite` |
| Requirement 7 | Analytical SQL queries / data analysis | [src/queries/analytical_queries.sql](src/queries/analytical_queries.sql) | `tests/test_backend.py::QueryRegistryTests.test_official_queries_are_read_only_and_runnable_in_sqlite` |
| Requirement 8 | Index recommendations and performance-oriented access paths | [src/schema/indexing.sql](src/schema/indexing.sql), [README.md](README.md) | `tests/test_backend.py::InitializationTests.test_initialization_builds_indexes_and_clean_audit` confirms indexes are actually created |
| Requirement 9 | Working prototype / interface / integrated system | [src/web_server.py](src/web_server.py), [pawtrack_demo.html](pawtrack_demo.html) | `tests/test_backend.py::WorkflowTests`, `tests/test_backend.py::HttpSmokeTests` |
| Bonus | LLM + Database integration: architecture refinement and prompt-to-SQL generation | [src/LLM_DATABASE_BONUS.md](src/LLM_DATABASE_BONUS.md), [src/llm_sql_assistant.py](src/llm_sql_assistant.py), [src/llm_prompt_cases.json](src/llm_prompt_cases.json), [pawtrack_demo.html](pawtrack_demo.html) | `tests/test_backend.py::QueryRegistryTests.test_glm_generated_query_executes_after_validation_with_fake_client`, `tests/test_backend.py::QueryRegistryTests.test_glm_generated_query_rejects_unsafe_sql`, `tests/test_backend.py::HttpSmokeTests.test_glm_generate_query_reports_missing_api_key` |

## Implementation Notes

- The ER design, table set, field set, primary keys, foreign keys, and relationship structure were preserved.
- Schema hardening was limited to declarative constraints consistent with the existing design:
  - `CHECK` constraints for controlled domains and same-row temporal rules
  - `UNIQUE` on `ADOPTION_RECORD.application_id` to enforce the documented 1:0..1 relationship
- Indexes from [src/schema/indexing.sql](src/schema/indexing.sql) are now executed during initialization instead of remaining documentation-only.
- Official SQL deliverables are now SQLite-native and run directly without runtime dialect rewriting.
- Mutation examples used for workflow explanation were moved to [src/WORKFLOW_SQL_EXAMPLES.md](src/WORKFLOW_SQL_EXAMPLES.md); the official query files remain read-only `SELECT` statements.
- The LLM bonus architecture section uses GLM as a design-review assistant and presents the original-vs-refined database comparison through `GET /api/llm-bonus`.
- The GLM prompt-to-SQL path validates generated SQL with static checks, `EXPLAIN QUERY PLAN`, a read-only SQLite connection, and a SQLite authorizer before returning rows.

## Verification Commands

```powershell
python src\web_server.py --reset-db
python -m unittest discover -s tests -v
python -m py_compile src\web_server.py src\mcp_server.py src\query_registry.py src\llm_sql_assistant.py src\llm_prompt_eval.py
python src\llm_prompt_eval.py --methods zero_shot schema_grounded few_shot self_check_repair
```

## Current Snapshot

Current seed-data counts after rebuild on April 23, 2026:

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

Operational status snapshot on April 23, 2026:

| Domain | Distribution |
|---|---|
| `PET.status` | `available=11`, `reserved=1`, `medical_hold=2`, `adopted=6` |
| `ADOPTION_APPLICATION.status` | `Under Review=3`, `Approved=6`, `Rejected=6` |
| `FOLLOW_UP.result_status` | `Excellent=2`, `Good=6`, `Satisfactory=2`, `Needs Improvement=6` |
