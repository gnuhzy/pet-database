# Pet Adoption Center Management System
> CSC 3170 Database Project — Group [X] | CUHK 2026
 
## Table of Contents
1. [Project Overview](#project-overview)
2. [ER Design](#er-design)
3. [Relational Schema & Normalization](#relational-schema--normalization)
4. [Sample Data](#sample-data)
5. [Backend & SQL Queries](#backend--sql-queries)
6. [Frontend Demo](#frontend-demo)
7. [Bonus](#bonus)
8. [How to Run](#how-to-run)
 
---
 
## Project Overview
 
This project implements a database management system for a pet adoption center. The system supports the full operational workflow of a shelter, including pet registration, adoption applications, post-adoption follow-up, medical and vaccination records, and volunteer care scheduling.
 
The database was designed following standard normalization principles (3NF/BCNF) and implemented with a web-based frontend demo for demonstrating daily operations.
 
---

 
## ER Design
 
> See the file [ER Design for the Pet Adoption Center Management System.md](https://github.com/gnuhzy/pet-database/blob/2bcc63b18d6a3502cbfa35ccb2c622ac1ef64467/ER%20Design%20for%20the%20Pet%20Adoption%20Center%20Management%20System.md)
 
<!--
Suggested content:
- Brief explanation of design decisions and assumptions
- List of entities and their roles
- Description of key relationships and cardinalities
- Embedded ER diagram image: ![ER Diagram](./assets/er_diagram.png)
-->
 
---
 
## Relational Schema & Normalization
 
> See the file [ER Design for the Pet Adoption Center Management System.md](https://github.com/gnuhzy/pet-database/blob/2bcc63b18d6a3502cbfa35ccb2c622ac1ef64467/ER%20Design%20for%20the%20Pet%20Adoption%20Center%20Management%20System.md)
 
<!--
Suggested content:
- Full relational schemas with primary keys (underlined) and foreign keys noted
- Functional dependencies for each relation
- Normalization analysis (justify 3NF or BCNF for each table)
- Any indexing or hashing recommendations (Project requirement #8)
-->
 
---
 
## Sample Data
 
> *To be completed by the data member.*
 
<!--
Suggested content:
- Description of how data was generated (realistic assumptions made)
- Number of records per table
- Any notable data constraints or edge cases covered
- Link to SQL seed file: [seed.sql](./sql/seed.sql)
-->
 
---
 
## Backend & SQL Queries
 
The browser-facing backend is implemented in `src/web_server.py` using Python's standard library HTTP server and SQLite. On first run, it creates `pet_database.db` from `src/schema/table.sql` and imports the seed records from `data/*.csv`.

The API exposes JSON endpoints for the frontend modules:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/dashboard` | Dashboard statistics, pet status overview, recent activity |
| `GET /api/analytics` | Occupancy, long-stay pets, approval rates, species demand, volunteer workload, follow-up outcomes |
| `GET /api/pets` | Pet list joined with shelter names |
| `GET /api/applicants` | Applicant dropdown data |
| `GET /api/applications` | Adoption applications joined with applicant and pet names |
| `POST /api/applications` | Create a new pending application and reserve the selected pet |
| `PATCH /api/applications/{id}/review` | Approve or reject a pending application |
| `GET /api/medical-records` | Medical visit history |
| `GET /api/vaccinations?upcoming=true` | Vaccination due dates |
| `GET /api/volunteers` | Volunteer roster with assigned pets |
| `GET /api/care-assignments` | Care assignment schedule |
| `GET /api/llm-bonus` | LLM-assisted design refinement, integrity audit, prompt patterns, query catalog |
| `POST /api/llm-query` | Safe natural-language query routing to predefined read-only SQL |

The existing MCP server in `src/mcp_server.py` is kept for the LLM/database bonus workflow and uses the same SQLite database file.
 
---
 
## Frontend Demo
 
The frontend is a self-contained single-file HTML demo (`pawtrack_demo.html`) that simulates the full management interface of the adoption center. It is built with plain HTML, CSS, and JavaScript — no frameworks or external dependencies are required.
 
### What it demonstrates
 
The demo covers five core modules drawn directly from the ER schema:
 
| Module | Entities covered | Key interactions |
|--------|-----------------|-----------------|
| Dashboard | — | Live statistics, recent activity feed, pet status overview |
| Pet management | `PET`, `SHELTER` | Searchable and filterable pet list, full pet profile view |
| Adoption applications | `ADOPTION_APPLICATION`, `APPLICANT` | New application form, application review (Approve / Reject) |
| Medical records | `MEDICAL_RECORD`, `VACCINATION` | Visit history, upcoming vaccination due dates |
| Volunteers | `VOLUNTEER`, `CARE_ASSIGNMENT` | Volunteer roster, daily care assignment schedule |
| Analytics | All core entities | Occupancy, long-stay, approval-rate, demand, workload, and follow-up analysis |
 
### API integration strategy
 
The demo now loads its data through `fetch('/api/...')` calls instead of browser-side mock arrays. Search and filtering still run client-side for responsiveness, while mutations such as creating an adoption application and reviewing an application are sent to the backend and persisted in SQLite.
 
### Key interactions
 
**Submitting a new adoption application**
 
Clicking `+ New application` opens a modal form. The pet dropdown is dynamically populated with only `Available` pets, enforcing the business rule from the ER design that a reserved or adopted pet cannot receive new applications. On submission, the selected pet's status is updated to `reserved`, mirroring the SQL transaction:
 
```sql
INSERT INTO ADOPTION_APPLICATION (applicant_id, pet_id, ...) VALUES (...);
UPDATE PET SET status = 'reserved' WHERE pet_id = ?;
```
 
**Reviewing a pending application**
 
Each `Pending` application displays a `Review` button. The reviewer must enter a decision note before choosing Approve or Reject — empty submissions are blocked. On confirmation, the application's status, reviewer name, reviewed date, and decision note are all updated in one operation, corresponding to:
 
```sql
UPDATE ADOPTION_APPLICATION
SET status = ?, reviewer_name = ?, reviewed_date = ?, decision_note = ?
WHERE application_id = ?;
```
 
### File structure
 
```
pawtrack_demo.html      ← frontend single-page interface
src/web_server.py       ← HTTP JSON API and SQLite initializer
pet_database.db         ← generated locally on first backend run
```
 
### How to open
 
Start the backend server, then open the frontend URL it prints:
 
```bash
python3 src/web_server.py
```
 
Then visit `http://127.0.0.1:8000/pawtrack_demo.html`. If the HTML file is opened directly with `file://`, it will still try to connect to `http://127.0.0.1:8000`.
 
---
 
## Bonus
 
This project chooses **Option A — LLM + Database**.

The implementation has two parts:

1. **LLM-assisted database architecture refinement**
   - `GET /api/llm-bonus` returns a documented comparison between the original schema design and the refined design.
   - The refinement covers controlled status domains, workflow consistency, anomaly detection, efficient access paths, and safe LLM query routing.
   - The backend runs integrity and anomaly checks such as invalid status values, reserved pets without pending applications, capacity overflow, and adoption records linked to non-approved applications.

2. **Prompt-guided database querying**
   - `POST /api/llm-query` accepts a natural-language prompt and routes it to a reviewed predefined `SELECT` query from `src/queries`.
   - The system deliberately avoids executing arbitrary LLM-generated SQL.
   - `src/mcp_server.py` exposes the same query registry through MCP tools: `list_available_queries`, `execute_named_query`, and `natural_language_query`.

The frontend includes an **LLM Bonus** page that displays the refinement comparison, integrity audit, prompt engineering patterns, query catalog, and an interactive natural-language query assistant.

Detailed bonus documentation is in `src/LLM_DATABASE_BONUS.md`.
 
---
 
## How to Run
 
### Prerequisites
- Python 3.10+
 
### 1. Install optional MCP dependency
```bash
pip install -r requirements.txt
```
 
### 2. Start the backend server
```bash
python3 src/web_server.py
```
 
To rebuild the SQLite database from the CSV seed files:

```bash
python3 src/web_server.py --reset-db
```

### 3. Open the frontend
Navigate to `http://127.0.0.1:8000/pawtrack_demo.html` in your browser.

---

# 宠物领养中心管理系统
> CSC 3170 数据库项目 — 第 [X] 组 | 香港中文大学 2026

## 目录
1. [项目概述](#项目概述)
2. [ER 图设计](#er-图设计)
3. [关系模式与规范化](#关系模式与规范化)
4. [样本数据](#样本数据)
5. [后端与 SQL 查询](#后端与-sql-查询)
6. [前端演示](#前端演示)
7. [附加加分项](#附加加分项)
8. [运行说明](#运行说明)

---

## 项目概述

本项目为一家宠物领养中心设计并实现了一套数据库管理系统，覆盖收容所日常运营的完整业务流程，包括宠物档案注册、领养申请处理、领养后跟进记录、医疗与疫苗管理，以及志愿者护理排班。

数据库设计遵循标准规范化原则（3NF/BCNF），并配有基于网页的前端演示界面，用于展示系统的日常操作功能。

---


## ER 图设计

> **

<!--
建议包含以下内容：
- 设计决策说明与假设条件阐述
- 各实体的定义及其在业务中的作用
- 关键关系及其基数说明
- 嵌入 ER 图图片：![ER 图](./assets/er_diagram.png)
-->

---

## 关系模式与规范化

> **

<!--
建议包含以下内容：
- 完整关系模式列表（注明主键和外键）
- 各关系的函数依赖分析
- 规范化说明（论证每张表满足 3NF 或 BCNF）
- 索引与哈希建议（对应项目要求第 8 项）
-->

---

## 样本数据

> **

<!--
建议包含以下内容：
- 数据生成方式说明（真实性假设与依据）
- 各表的记录数量
- 数据中覆盖的特殊约束或边界情况
- SQL 种子文件链接：[seed.sql](./sql/seed.sql)
-->

---

## 后端与 SQL 查询

面向浏览器前端的后端服务位于 `src/web_server.py`，使用 Python 标准库 HTTP Server + SQLite 实现。首次启动时，服务会读取 `src/schema/table.sql` 建表，并从 `data/*.csv` 导入种子数据，生成本地数据库 `pet_database.db`。

主要接口如下：

| 接口 | 用途 |
|------|------|
| `GET /api/dashboard` | 仪表盘统计、宠物状态分布、近期动态 |
| `GET /api/analytics` | 入住率、长期滞留、批准率、物种需求、志愿者工作量、跟进结果分析 |
| `GET /api/pets` | 宠物列表，并关联收容所名称 |
| `GET /api/applicants` | 申请人下拉列表数据 |
| `GET /api/applications` | 领养申请列表，并关联申请人和宠物名称 |
| `POST /api/applications` | 新建待审核申请，同时将宠物状态更新为 reserved |
| `PATCH /api/applications/{id}/review` | 通过或拒绝待审核申请 |
| `GET /api/medical-records` | 医疗访问记录 |
| `GET /api/vaccinations?upcoming=true` | 疫苗到期提醒 |
| `GET /api/volunteers` | 志愿者列表及分配宠物 |
| `GET /api/care-assignments` | 护理任务排班 |
| `GET /api/llm-bonus` | LLM 辅助设计优化、完整性审计、prompt 模式、查询目录 |
| `POST /api/llm-query` | 将自然语言安全路由到预定义只读 SQL 查询 |

原有的 `src/mcp_server.py` 仍保留，用于 LLM 与数据库结合的加分项流程，并复用同一个 SQLite 数据库文件。

---

## 前端演示

前端为一个完全独立的单文件 HTML 演示页面（`pawtrack_demo.html`），模拟了领养中心管理系统的完整操作界面。页面使用纯 HTML、CSS 和 JavaScript 编写，无需任何框架或外部依赖。

### 功能模块概览

演示页面涵盖五个核心模块，均直接对应 ER 图中的实体设计：

| 模块 | 涉及实体 | 主要交互功能 |
|------|---------|------------|
| 仪表盘 | — | 实时统计数字、近期动态记录、宠物状态分布概览 |
| 宠物管理 | `PET`、`SHELTER` | 可搜索/筛选的宠物列表，宠物完整档案查看 |
| 领养申请 | `ADOPTION_APPLICATION`、`APPLICANT` | 新建申请表单，申请审核（通过 / 拒绝） |
| 医疗记录 | `MEDICAL_RECORD`、`VACCINATION` | 医疗访问历史，即将到期的疫苗接种提醒 |
| 志愿者管理 | `VOLUNTEER`、`CARE_ASSIGNMENT` | 志愿者名单，当日护理分配排班 |
| 分析面板 | 核心业务实体 | 入住率、长期滞留、批准率、领养需求、工作量与跟进结果分析 |

### API 对接策略

演示页面已改为通过 `fetch('/api/...')` 从后端读取真实数据，不再依赖浏览器内写死的 Mock 数组。搜索和筛选仍保留在前端执行以提升响应速度；新建领养申请、审核申请等会改变数据的操作，则会发送到后端并持久化到 SQLite。

### 核心交互说明

**新建领养申请**

点击 `+ New application` 按钮打开表单弹窗。宠物下拉列表会动态过滤，仅显示状态为 `Available` 的宠物，从前端层面落实了 ER 设计中"已预留或已领养的宠物不可接受新申请"的业务规则。

提交后，所选宠物的状态将同步更新为 `reserved`，对应以下数据库事务：

```sql
INSERT INTO ADOPTION_APPLICATION (applicant_id, pet_id, application_date, reason, status)
VALUES (?, ?, ?, ?, 'Under Review');

UPDATE PET
SET status = 'reserved'
WHERE pet_id = ?;
```

**审核领养申请**

所有状态为 `Pending` 的申请行会显示 `Review` 审核按钮。审核员必须填写审核备注后，方可点击通过或拒绝——系统会拦截空备注的提交，避免无记录的审核操作。

确认后，申请的状态、审核人姓名、审核日期和审核备注将一并更新，对应以下 SQL 操作：

```sql
UPDATE ADOPTION_APPLICATION
SET status        = ?,
    reviewer_name = ?,
    reviewed_date = ?,
    decision_note = ?
WHERE application_id = ?;
```

### 文件结构

```
pawtrack_demo.html      ← 前端单页界面
src/web_server.py       ← HTTP JSON API 与 SQLite 初始化逻辑
pet_database.db         ← 后端首次启动后本地生成
```

### 打开方式

先启动后端服务：

```bash
python3 src/web_server.py
```

然后在浏览器中访问 `http://127.0.0.1:8000/pawtrack_demo.html`。如果直接用 `file://` 打开 HTML，它也会尝试连接 `http://127.0.0.1:8000` 的后端接口。

---

## 附加加分项

本项目选择 **方案一：大语言模型（LLM）与数据库结合**。

实现分为两个部分：

1. **LLM 辅助数据库架构优化**
   - `GET /api/llm-bonus` 返回原始设计与优化后设计的对比。
   - 优化内容包括状态字段约束、业务流程一致性、异常数据检测、高频访问索引、安全查询路由等。
   - 后端会检测异常情况，例如非法状态值、reserved 宠物没有待审核申请、收容所超容量、领养记录关联非 approved 申请等。

2. **Prompt 引导的数据库查询**
   - `POST /api/llm-query` 接收自然语言问题，并将其路由到 `src/queries` 中经过审核的预定义 `SELECT` 查询。
   - 系统不执行任意 LLM 生成的 SQL，从而降低 SQL 注入、表名幻觉和误更新风险。
   - `src/mcp_server.py` 同时通过 MCP 提供 `list_available_queries`、`execute_named_query` 和 `natural_language_query`。

前端新增 **LLM Bonus** 页面，用于展示架构优化对比、完整性审计、prompt 设计模式、查询目录，以及交互式自然语言查询助手。

详细说明见 `src/LLM_DATABASE_BONUS.md`。

---

## 运行说明

### 环境要求
- Python 3.10+

### 第一步：安装可选 MCP 依赖
```bash
pip install -r requirements.txt
```

### 第二步：启动后端服务器
```bash
python3 src/web_server.py
```

如需重新从 CSV 种子数据生成数据库：

```bash
python3 src/web_server.py --reset-db
```

### 第三步：打开前端页面
在浏览器中访问 `http://127.0.0.1:8000/pawtrack_demo.html`。
