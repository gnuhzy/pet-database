# Pet Adoption Center Management System
> CSC 3170 Database Project | CUHK 2026

## Project Overview

This project designs and implements a database-backed management system for a pet adoption center. It supports shelter capacity monitoring, pet records, adoption applications, finalized adoption records, follow-up visits, medical and vaccination history, volunteer scheduling, analytics, and an LLM/database bonus module.

The database follows a normalized relational design and is implemented with SQLite. The frontend is a single-page HTML application backed by `src/web_server.py`.

## Project Requirement Coverage

| Project requirement | Where it is covered |
|---------------------|---------------------|
| 1. Analyze organization and application requirements | ER design document sections 1-3 |
| 2. Identify entities, attributes, relationships, constraints | ER design document and `src/schema/table.sql` |
| 3. Produce an E-R diagram | `src/diagrams/mermaid-ER-diagram.png` |
| 4. Convert ER diagram to relational schemas with keys, dependencies, and normalization | `ER Design for the Pet Adoption Center Management System.md` and `src/schema/table.sql` |
| 5. Populate schemas with realistic data | `data/*.csv` |
| 6. Daily operational SQL queries | `src/queries/operational_queries.sql` |
| 7. Analytical/data-mining SQL queries | `src/queries/analytical_queries.sql` and the Analytics page |
| 8. Indexing/hashing suggestions and explanation | `src/schema/indexing.sql` |
| 9. Implement 4-6 and optional 7 | `src/web_server.py`, `src/mcp_server.py`, `pawtrack_demo.html` |
| LLM + Database bonus | `src/LLM_DATABASE_BONUS.md`, `/api/llm-bonus`, `/api/llm-query`, and MCP tools |

Items that still require group-specific input for the final submission are the group member list, coordinator name, individual contributions, presentation slides, references, and final report narrative.

## Schema And Data

The schema is implemented in `src/schema/table.sql` and includes:

| Relation | Primary key | Main relationships |
|----------|-------------|--------------------|
| `SHELTER` | `shelter_id` | Parent of pets and volunteers |
| `PET` | `pet_id` | Belongs to one shelter |
| `APPLICANT` | `applicant_id` | Submits adoption applications |
| `ADOPTION_APPLICATION` | `application_id` | Links applicant and pet |
| `ADOPTION_RECORD` | `adoption_id` | Final record for an approved application |
| `FOLLOW_UP` | `followup_id` | Belongs to one adoption record |
| `MEDICAL_RECORD` | `record_id` | Belongs to one pet |
| `VACCINATION` | `vaccination_id` | Belongs to one pet |
| `VOLUNTEER` | `volunteer_id` | Belongs to one shelter |
| `CARE_ASSIGNMENT` | `assignment_id` | Links volunteer and pet care work |

The seed data under `data/` covers all ten relations and includes available, reserved, adopted, and medical-hold pets; approved, rejected, and under-review applications; follow-up outcomes; vaccination due dates; and volunteer assignments.

## Backend API

The backend uses Python standard-library HTTP server plus SQLite. On startup it creates the database if needed, loads CSV seed data, reconciles workflow state, and applies `src/schema/indexing.sql`.

Main endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/dashboard` | Dashboard statistics and recent activity |
| `GET /api/options` | Shared frontend/backend domain options |
| `GET /api/analytics` | Analytical reports |
| `GET /api/pets` | Pet list |
| `GET /api/applicants` | Applicant list |
| `GET /api/applications` | Adoption applications |
| `POST /api/applications` | Create an adoption application and reserve the pet |
| `PATCH /api/applications/{id}/review` | Approve or reject an application |
| `GET /api/adoption-records` | Final adoption records |
| `GET /api/follow-ups` | Follow-up records |
| `POST /api/follow-ups` | Create a follow-up |
| `GET /api/medical-records` | Medical records |
| `GET /api/vaccinations` | Vaccination records |
| `GET /api/vaccinations?upcoming=true` | Vaccinations due within 30 days or overdue |
| `GET /api/volunteers` | Volunteer list |
| `GET /api/care-assignments` | Care assignments |
| `GET /api/llm-bonus` | LLM refinement, audit checks, prompt patterns, query catalog |
| `POST /api/llm-query` | Safe natural-language routing to reviewed read-only SQL |

## Frontend Demo

`pawtrack_demo.html` is a single-page management interface. It no longer uses hard-coded business data; it loads from the backend through `fetch('/api/...')`. It supports CRUD-style operations for the main ER entities, adoption application review, follow-up creation, dashboard activity, analytics, and the LLM bonus page.

Dates are entered as `YYYY-MM-DD` text fields to avoid browser-locale placeholders. Frontend validation mirrors backend rules for key workflows such as duplicate care assignments, future dates, adoption status transitions, and cross-shelter care assignments.

## LLM + Database Bonus

This project implements the LLM + Database bonus:

1. LLM-assisted schema refinement: `/api/llm-bonus` documents refined constraints, indexing decisions, workflow consistency rules, and anomaly detection.
2. Prompt-guided query access: `/api/llm-query` and `src/mcp_server.py` route natural-language prompts to reviewed read-only SQL queries instead of executing arbitrary generated SQL.

Full details are in `src/LLM_DATABASE_BONUS.md`.

## Running

```bash
python3 src/web_server.py
```

Then open:

```text
http://127.0.0.1:8000/pawtrack_demo.html
```

To rebuild the local database from CSV seed data:

```bash
python3 src/web_server.py --reset-db
```
