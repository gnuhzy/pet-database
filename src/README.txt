src/
├── diagrams/
│   └── mermaid-ER-diagram.png
│
├── insert_data/
│   ├── insert_shelter.sql
│   ├── insert_applicant.sql
│   ├── insert_pet.sql
│   ├── insert_volunteer.sql
│   ├── insert_vaccination.sql
│   ├── insert_medical_record.sql
│   ├── insert_adoption_application.sql
│   ├── insert_care_assignment.sql
│   ├── insert_adoption_record.sql
│   └── insert_follow_up.sql
│
├── queries/
│   ├── operational_queries.sql
│   └── analytical_queries.sql
│
├── schema/
│   ├── table.sql
│   └── indexing.sql
│
├── LLM_DATABASE_BONUS.md
├── MCP.md
├── README.txt
├── WORKFLOW_SQL_EXAMPLES.md
├── llm_sql_assistant.py
├── llm_prompt_cases.json
├── llm_prompt_eval.py
├── llm_prompt_results.json
├── mcp_server.py
├── query_registry.py
└── web_server.py

Notes
- `web_server.py` is the main runtime entry point.
- `query_registry.py` is the shared read-only SQL catalog used by both the web API and the MCP server.
- `llm_sql_assistant.py` implements GLM prompt-to-SQL generation and strict read-only SQL validation.
- `llm_prompt_cases.json`, `llm_prompt_eval.py`, and `llm_prompt_results.json` provide prompt-method evaluation evidence.
- `WORKFLOW_SQL_EXAMPLES.md` keeps write-side examples outside the official read-only query registry.
- `schema/indexing.sql` is executed during initialization, not just documented.
