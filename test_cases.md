# Pet Database Backend Test Cases

## Test Overview

These tests cover daily operations, analytical queries, referential integrity, and frontend/backend workflow behavior for the PawTrack web demo.

## SQL 方言说明 (SQL Dialect Note)

项目 SQL 文件和本测试用例使用 MySQL 风格的日期函数（`CURDATE()`、
`DATE_ADD(..., INTERVAL n DAY)`、`DATEDIFF(...)`）。实际后端 `src/web_server.py`
使用 SQLite，并在 `normalize_sql()` 中自动将上述函数转换为 SQLite 等价形式
（`date('now')`、`date('now','+n day')`、`julianday(...)` 差值）。因此：

- 通过后端 API / MCP 运行这些测试用例时，SQL 会自动适配。
- 若直接用 `sqlite3` CLI 手动执行 SQL 文件，请先按上述映射替换日期函数，
  或使用 `/api/llm-query` 端点让后端完成归一化。

---

The SQL query files contain a small amount of MySQL-style date syntax:

- `CURDATE()`
- `DATE_ADD(CURDATE(), INTERVAL n DAY)`
- `DATEDIFF(CURDATE(), date_column)`

The backend and MCP server normalize these expressions to SQLite-compatible local-date expressions before execution.

## Shelter Management

### TC-SM-01: View Shelter Occupancy

Objective: verify that managers can monitor active pet count and capacity pressure.

Expected result:

- all shelters are returned
- active pets are counted from `available`, `reserved`, and `medical_hold`
- occupancy rate is ordered from highest to lowest

### TC-SM-02: Add A Shelter

Objective: verify that valid shelter data can be added.

Expected result:

- capacity must be a positive integer
- shelters linked to pets or volunteers cannot be deleted

## Pet Management

### TC-PET-01: View Pets In One Shelter

Expected result:

- only pets in the selected shelter are returned
- rows are ordered by intake date

### TC-PET-02: View Adoptable Pets

Expected result:

- only `available` pets appear in the adoption picker
- reserved, adopted, and medical-hold pets cannot receive new applications

### TC-PET-03: Enforce Pet Status Workflow

Expected result:

- new pets can start only as `available` or `medical_hold`
- `reserved` is produced by creating an adoption application
- `adopted` is produced by approving an adoption application
- direct edits cannot bypass the adoption workflow

## Adoption Workflow

### TC-AD-01: View Pending Applications

Expected result:

- all `Under Review` applications are listed as `Pending`
- each row includes applicant and pet information

### TC-AD-02: Create An Application

Expected result:

- only available pets can be selected
- the application is inserted as `Under Review`
- the pet is updated to `reserved`
- duplicate active applications are rejected

### TC-AD-03: Approve An Application

Expected result:

- only pending applications can be reviewed
- approval creates one adoption record
- final adoption fee must be finite and non-negative
- other pending applications for the same pet are closed
- the pet becomes adopted

### TC-AD-04: Reject An Application

Expected result:

- rejection records reviewer, reviewed date, and decision note
- if no pending applications remain, the pet returns to available

## Medical And Vaccination Records

### TC-MED-01: View Health History

Expected result:

- medical and vaccination records are joined to pets
- visit and vaccination dates are visible

### TC-MED-02: View Upcoming Vaccinations

Expected result:

- records with `next_due_date` within 30 days or overdue are returned
- rows are ordered by due date

### TC-MED-03: Validate Health Dates

Expected result:

- medical visit date cannot be before pet intake date
- medical visit date cannot be in the future
- vaccination date cannot be before pet intake date
- vaccination date cannot be in the future
- next due date cannot be before vaccination date

## Volunteer Scheduling

### TC-VOL-01: View Volunteer Assignments

Expected result:

- rows include volunteer, pet, date, shift, task, and status

### TC-VOL-02: Enforce Assignment Rules

Expected result:

- volunteer and pet must exist
- volunteer and pet must belong to the same shelter
- assignment date cannot be before pet intake date
- assignment date cannot be before volunteer join date
- completed assignments cannot be dated in the future
- duplicate volunteer-pet-date-shift slots are rejected

### TC-VOL-03: Analyze Workload

Expected result:

- total, completed, cancelled, and scheduled assignments are counted per volunteer

## Follow-Up

### TC-FU-01: View Follow-Ups

Expected result:

- follow-ups are linked to confirmed adoption records
- applicant and pet information is visible through joins

### TC-FU-02: Add A Follow-Up

Expected result:

- referenced adoption record must exist
- follow-up date cannot be before adoption date
- follow-up date cannot be in the future
- follow-up type, pet condition, and result status are required

## Analytical Queries

### TC-AN-01: Shelter Occupancy

Expected result: active pet count and occupancy rate are calculated for every shelter.

### TC-AN-02: Approval Rate By Housing Type

Expected result: applications are grouped by applicant housing type.

### TC-AN-03: Adoption Demand By Species

Expected result: applications and successful adoptions are grouped by pet species.

### TC-AN-04: Long-Stay Pets

Expected result: available pets are ordered by days in shelter.

## Referential Integrity Tests

| Test item | Invalid operation | Expected result |
|-----------|-------------------|-----------------|
| `FK_VOLUNTEER_SHELTER` | Insert `VOLUNTEER.shelter_id = 999` | Rejected |
| `FK_PET_SHELTER` | Insert `PET.shelter_id = 999` | Rejected |
| `FK_VACCINATION_PET` | Insert `VACCINATION.pet_id = 999` | Rejected |
| `FK_MEDICAL_RECORD_PET` | Insert `MEDICAL_RECORD.pet_id = 999` | Rejected |
| `FK_CARE_ASSIGNMENT_VOLUNTEER` | Insert `CARE_ASSIGNMENT.volunteer_id = 999` | Rejected |
| `FK_CARE_ASSIGNMENT_PET` | Insert `CARE_ASSIGNMENT.pet_id = 999` | Rejected |
| `FK_ADOPTION_APPLICATION_APPLICANT` | Insert `ADOPTION_APPLICATION.applicant_id = 999` | Rejected |
| `FK_ADOPTION_APPLICATION_PET` | Insert `ADOPTION_APPLICATION.pet_id = 999` | Rejected |
| `FK_ADOPTION_RECORD_APPLICATION` | Insert `ADOPTION_RECORD.application_id = 999` | Rejected |
| `FK_FOLLOW_UP_ADOPTION` | Insert `FOLLOW_UP.adoption_id = 999` | Rejected |
