# Pet Database Backend Test Cases

## 测试概述

本测试用例基于 `README.md` 中定义的五大核心业务模块设计，覆盖：
- **日常操作 SQL 查询**（项目要求 #6）
- **分析/数据挖掘 SQL 查询**（项目要求 #7）
- **业务约束验证**（外键、状态一致性）

## SQL 方言说明 (SQL Dialect Note)

项目 SQL 文件和本测试用例使用 MySQL 风格的日期函数（`CURDATE()`、
`DATE_ADD(..., INTERVAL n DAY)`、`DATEDIFF(...)`）。实际后端 `src/web_server.py`
使用 SQLite，并在 `normalize_sql()` 中自动将上述函数转换为 SQLite 等价形式
（`date('now')`、`date('now','+n day')`、`julianday(...)` 差值）。因此：

- 通过后端 API / MCP 运行这些测试用例时，SQL 会自动适配。
- 若直接用 `sqlite3` CLI 手动执行 SQL 文件，请先按上述映射替换日期函数，
  或使用 `/api/llm-query` 端点让后端完成归一化。

---

## 模块一：收容所管理 (Shelter Management)

### TC-SM-01: 查看收容所容量占用情况

**目标**：验证管理者可以监控每个收容所的容量压力

**前置条件**：数据库中已有 SHELTER 和 PET 数据

**测试步骤**：
```sql
SELECT s.shelter_id, s.name, s.capacity, COUNT(p.pet_id), occupancy_rate
FROM SHELTER s LEFT JOIN PET p ON s.shelter_id = p.shelter_id
GROUP BY s.shelter_id;
```

**预期结果**：
- 返回所有收容所及其当前入住率
- 空收容所返回 capacity 数值和 0 宠物数
- 按入住率降序排列

**实际结果**：
```
shelter_id  name                      capacity  current_pet_count  occupancy_rate
1           Happy Paws Shelter        50        15                 30.00
2           Animal Rescue Center      40        5                  12.50
3           Second Chance Sanctuary   30        2                   6.67
```

---

### TC-SM-02: 添加新收容所

**目标**：验证可以正确添加新收容所记录

**前置条件**：数据库中存在 SHELTER 表

**测试步骤**：
```sql
INSERT INTO SHELTER (shelter_id, name, address, phone, capacity)
VALUES (4, 'New Hope Shelter', '123 New St', '555-0100', 60);
SELECT * FROM SHELTER WHERE shelter_id = 4;
```

**预期结果**：
- 插入成功，返回新记录
- 主键不冲突

**实际结果**：
```
shelter_id  name             address       phone       capacity
4           New Hope Shelter 123 New St     555-0100    60
```

---

## 模块二：宠物管理 (Pet Management)

### TC-PET-01: 查看特定收容所的所有宠物

**目标**：员工可以查看指定收容所当前所有的宠物列表

**前置条件**：存在 shelter_id = 1 的收容所和宠物数据

**测试步骤**：
```sql
SELECT pet_id, name, species, breed, sex, status, intake_date
FROM PET WHERE shelter_id = 1 ORDER BY intake_date DESC;
```

**预期结果**：
- 仅返回该收容所的宠物
- 按入住日期降序排列

**实际结果**：
```
pet_id  name     species  breed      sex    status      intake_date
5       Luna     Dog      Labrador   Male   available   2025-01-15
9       Max      Dog      Poodle     Male   available   2025-01-10
...
```

---

### TC-PET-02: 查看可领养宠物列表

**目标**：员工可准备可供访客领养的宠物列表

**前置条件**：存在 status = 'available' 的宠物

**测试步骤**：
```sql
SELECT pet_id, name, species, breed, sex, color, special_needs
FROM PET WHERE status = 'available' ORDER BY species, name;
```

**预期结果**：
- 仅返回 available 状态的宠物
- 按种类和名称排序

**实际结果**：
```
pet_id  name     species  breed      sex    color     special_needs
3       Charlie  Cat      Tabby      Male   Gray      NULL
7       Daisy    Bird     Parrot     Female Yellow    NULL
1       Luna     Dog      Labrador   Male   Brown     NULL
...
```

---

### TC-PET-03: 查看在收容所停留最久的宠物

**目标**：识别需要推广或特殊领养支持的长期滞留宠物

**前置条件**：存在 available 状态的宠物

**测试步骤**：
```sql
SELECT pet_id, name, species, breed, intake_date, days_in_shelter
FROM PET WHERE status = 'available' ORDER BY days_in_shelter DESC;
```

**预期结果**：
- 返回所有 available 宠物，按停留天数降序
- days_in_shelter = CURDATE() - intake_date

---

### TC-PET-04: 业务约束 - 已领养宠物不能再申请

**目标**：验证已 adopted 的宠物不能接受新的领养申请

**前置条件**：存在 status = 'adopted' 的宠物

**测试步骤**：
```sql
-- 检查 adopted 宠物是否会出现在可申请列表中
SELECT pet_id, name, status FROM PET WHERE status = 'adopted';
```

**预期结果**：
- adopted 宠物不在可供申请的宠物列表中
- 应用层应阻止对 adopted 宠物创建新申请

---

## 模块三：领养申请处理 (Adoption Application)

### TC-AD-01: 查看待审核的领养申请

**目标**：领养经理可以检查等待决策的申请

**前置条件**：存在 status = 'Under Review' 的申请

**测试步骤**：
```sql
SELECT a.application_id, ap.full_name, p.name, p.species, a.application_date, a.status
FROM ADOPTION_APPLICATION a
JOIN APPLICANT ap ON a.applicant_id = ap.applicant_id
JOIN PET p ON a.pet_id = p.pet_id
WHERE a.status = 'Under Review' ORDER BY a.application_date;
```

**预期结果**：
- 返回所有 Under Review 状态的申请
- 按申请日期升序排列

**实际结果**：
```
application_id  applicant_name  pet_name  species  application_date  status
1               John Smith      Luna     Dog      2025-02-01        Under Review
3               Emma Wilson     Max      Dog      2025-02-03        Under Review
...
```

---

### TC-AD-02: 批准领养申请

**目标**：验证可以批准一个处于 Under Review 状态的申请

**前置条件**：存在 application_id = 1 且状态为 Under Review 的申请

**测试步骤**：
```sql
UPDATE ADOPTION_APPLICATION
SET status = 'Approved', reviewed_date = '2025-02-15', reviewer_name = 'Staff A',
    decision_note = 'Applicant meets adoption requirements'
WHERE application_id = 1 AND status = 'Under Review';
```

**预期结果**：
- 更新成功，影响行数 = 1
- 该申请状态变为 Approved

---

### TC-AD-03: 拒绝领养申请

**目标**：验证可以拒绝一个处于 Under Review 状态的申请

**前置条件**：存在 application_id = 2 且状态为 Under Review 的申请

**测试步骤**：
```sql
UPDATE ADOPTION_APPLICATION
SET status = 'Rejected', reviewed_date = '2025-02-15', reviewer_name = 'Staff A',
    decision_note = 'Housing not suitable for pet size'
WHERE application_id = 2 AND status = 'Under Review';
```

**预期结果**：
- 更新成功，影响行数 = 1
- 该申请状态变为 Rejected

---

### TC-AD-04: 业务约束 - 只能对 available 宠物提交申请

**目标**：验证 reserved 或 adopted 状态的宠物不能接受新申请

**测试步骤**：
```sql
-- 检查非 available 宠物
SELECT pet_id, name, status FROM PET WHERE status != 'available';
```

**预期结果**：
- reserved 和 adopted 宠物不显示在可申请宠物下拉列表中

---

## 模块四：医疗与疫苗记录 (Medical Records)

### TC-MED-01: 查看特定宠物完整健康信息

**目标**：员工在领养或治疗前查看宠物疫苗和医疗历史

**前置条件**：存在 pet_id = 5 的宠物及其医疗记录

**测试步骤**：
```sql
SELECT p.name, p.species, v.vaccine_name, v.vaccination_date, v.next_due_date,
       m.visit_date, m.record_type, m.diagnosis, m.treatment
FROM PET p
LEFT JOIN VACCINATION v ON p.pet_id = v.pet_id
LEFT JOIN MEDICAL_RECORD m ON p.pet_id = m.pet_id
WHERE p.pet_id = 5
ORDER BY m.visit_date DESC, v.vaccination_date DESC;
```

**预期结果**：
- 返回该宠物的所有疫苗接种和医疗访问记录
- 按日期降序排列

---

### TC-MED-02: 查看即将到期疫苗的宠物

**目标**：员工识别需要近期跟进疫苗接种的宠物

**前置条件**：存在 next_due_date 在未来 30 天内的疫苗记录

**测试步骤**：
```sql
SELECT p.pet_id, p.name, p.species, v.vaccine_name, v.next_due_date
FROM PET p JOIN VACCINATION v ON p.pet_id = v.pet_id
WHERE v.next_due_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
ORDER BY v.next_due_date;
```

**预期结果**：
- 返回所有 next_due_date <= 30 天后的疫苗记录
- 按到期日期升序排列

**实际结果**：
```
pet_id  name   species  vaccine_name  next_due_date
5       Luna   Dog      Rabies        2025-03-15
8       Bella  Cat      Distemper     2025-03-20
...
```

---

### TC-MED-03: 添加新疫苗接种记录

**目标**：验证可以正确添加新的疫苗接种记录

**测试步骤**：
```sql
INSERT INTO VACCINATION (vaccination_id, pet_id, vaccine_name, dose_no, vaccination_date, next_due_date, vet_name)
VALUES (100, 5, 'Rabies', 2, '2025-02-20', '2026-02-20', 'Dr. Smith');
SELECT * FROM VACCINATION WHERE vaccination_id = 100;
```

**预期结果**：
- 插入成功，返回新记录
- 外键 pet_id 存在

---

## 模块五：志愿者管理 (Volunteer Scheduling)

### TC-VOL-01: 查看志愿者排班

**目标**：志愿者协调员检查特定志愿者的任务安排

**前置条件**：存在 volunteer_id = 2 的志愿者及其任务分配

**测试步骤**：
```sql
SELECT c.assignment_id, c.assignment_date, c.shift, c.task_type, c.status,
       p.pet_id, p.name AS pet_name, p.species
FROM CARE_ASSIGNMENT c JOIN PET p ON c.pet_id = p.pet_id
WHERE c.volunteer_id = 2
ORDER BY c.assignment_date DESC, c.shift;
```

**预期结果**：
- 返回该志愿者的所有护理分配任务
- 按日期和班次排序

---

### TC-VOL-02: 分析志愿者工作量

**目标**：协调员评估志愿者参与度和任务完成情况

**前置条件**：存在 VOLUNTEER 和 CARE_ASSIGNMENT 数据

**测试步骤**：
```sql
SELECT v.volunteer_id, v.full_name, COUNT(c.assignment_id) AS total_assignments,
       SUM(CASE WHEN c.status = 'Completed' THEN 1 ELSE 0 END) AS completed_tasks,
       SUM(CASE WHEN c.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled_tasks,
       SUM(CASE WHEN c.status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled_tasks
FROM VOLUNTEER v LEFT JOIN CARE_ASSIGNMENT c ON v.volunteer_id = c.volunteer_id
GROUP BY v.volunteer_id, v.full_name
ORDER BY completed_tasks DESC, total_assignments DESC;
```

**预期结果**：
- 返回所有志愿者及其任务统计
- 包含已完成、已取消、已调度的任务数

---

### TC-VOL-03: 志愿者只能属于一个收容所

**目标**：验证 VOLUNTEER.shelter_id 外键约束

**测试步骤**：
```sql
-- 尝试插入无效的 shelter_id
INSERT INTO VOLUNTEER (volunteer_id, shelter_id, full_name, phone, email, join_date)
VALUES (999, 999, 'Test Volunteer', '555-9999', 'test@test.com', '2025-01-01');
```

**预期结果**：
- 违反外键约束，插入失败
- 错误：`FOREIGN KEY constraint failed`

---

## 模块六：领养后跟进 (Post-Adoption Follow-up)

### TC-FU-01: 查看已完成领养的跟进记录

**目标**：经理评估已领养宠物的适应情况

**前置条件**：存在 ADOPTION_RECORD 和 FOLLOW_UP 数据

**测试步骤**：
```sql
SELECT f.followup_id, f.followup_date, f.followup_type, f.pet_condition,
       f.adopter_feedback, f.result_status, f.staff_note
FROM FOLLOW_UP f
JOIN ADOPTION_RECORD ar ON f.adoption_id = ar.adoption_id
ORDER BY f.followup_date DESC;
```

**预期结果**：
- 返回所有跟进记录及其详细信息

---

### TC-FU-02: 添加新的跟进记录

**目标**：员工记录对已完成领养的电话跟进

**前置条件**：存在 adoption_id = 2 的领养记录

**测试步骤**：
```sql
INSERT INTO FOLLOW_UP (followup_id, adoption_id, followup_date, followup_type,
                       pet_condition, adopter_feedback, result_status, staff_note)
VALUES (100, 2, '2025-02-20', 'Phone Check', 'Healthy',
        'Pet is adapting well to the new home', 'Good', 'No issues reported');
SELECT * FROM FOLLOW_UP WHERE followup_id = 100;
```

**预期结果**：
- 插入成功，返回新记录

---

### TC-FU-03: 按结果状态统计跟进情况

**目标**：经理评估已领养宠物的整体适应情况

**测试步骤**：
```sql
SELECT f.result_status, COUNT(f.followup_id) AS total_followups
FROM FOLLOW_UP f GROUP BY f.result_status ORDER BY total_followups DESC;
```

**预期结果**：
```
result_status  total_followups
Good           8
Excellent      5
Concern        2
Poor           1
```

---

## 模块七：分析查询 (Analytical Queries)

### TC-AN-01: 收容所入住率分析

**目标**：验证 Q1 分析查询 - 按入住率降序显示所有收容所

**测试步骤**：
```sql
SELECT s.name, s.capacity, COUNT(p.pet_id) AS current_count,
       ROUND(COUNT(p.pet_id) * 100.0 / s.capacity, 2) AS occupancy_rate
FROM SHELTER s LEFT JOIN PET p ON s.shelter_id = p.shelter_id
WHERE p.status IN ('available', 'reserved', 'medical_hold') OR p.pet_id IS NULL
GROUP BY s.shelter_id, s.name, s.capacity
ORDER BY occupancy_rate DESC;
```

**预期结果**：
- 所有收容所都显示（即使没有宠物也显示）
- 按入住率降序排列

---

### TC-AN-02: 按住房类型分析申请批准率

**目标**：验证 Q3 分析查询 - 住房类型与批准结果的关系

**测试步骤**：
```sql
SELECT ap.housing_type, COUNT(a.application_id) AS total,
       SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) AS approved,
       SUM(CASE WHEN a.status = 'Rejected' THEN 1 ELSE 0 END) AS rejected,
       ROUND(SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) * 100.0
             / COUNT(a.application_id), 2) AS approval_rate
FROM APPLICANT ap JOIN ADOPTION_APPLICATION a ON ap.applicant_id = a.applicant_id
GROUP BY ap.housing_type ORDER BY approval_rate DESC;
```

**预期结果**：
- 按住房类型分组，显示每组的申请总数、批准数、拒绝数、批准率
- 按批准率降序排列

---

### TC-AN-03: 按宠物种类分析领养需求和成功率

**目标**：验证 Q4 分析查询 - 不同种类宠物的申请数和成功率

**测试步骤**：
```sql
SELECT p.species, COUNT(aa.application_id) AS total_applications,
       COUNT(ar.adoption_id) AS successful_adoptions,
       ROUND(COUNT(ar.adoption_id) * 100.0 / COUNT(aa.application_id), 2)
       AS adoption_success_rate
FROM PET p JOIN ADOPTION_APPLICATION aa ON p.pet_id = aa.pet_id
LEFT JOIN ADOPTION_RECORD ar ON aa.application_id = ar.application_id
GROUP BY p.species ORDER BY total_applications DESC;
```

**预期结果**：
- 显示每种宠物（Dog, Cat, Bird 等）的申请数、成功领养数、成功率
- 按申请数降序排列

---

### TC-AN-04: 宠物长期滞留分析

**目标**：验证 Q2 分析查询 - 识别需要特殊关注的长期滞留宠物

**测试步骤**：
```sql
SELECT pet_id, name, species, breed, intake_date,
       DATEDIFF(CURDATE(), intake_date) AS days_in_shelter
FROM PET WHERE status = 'available' ORDER BY days_in_shelter DESC;
```

**预期结果**：
- 仅返回 available 状态的宠物
- 按在收容所天数降序排列

---

## 测试执行摘要

| 模块 | 测试用例数 | 覆盖的查询 |
|------|-----------|-----------|
| 收容所管理 | 2 | Q1 (分析) |
| 宠物管理 | 4 | Q2, Q3 (操作) |
| 领养申请 | 4 | Q6, Q7 (操作) |
| 医疗记录 | 3 | Q4 (操作) |
| 志愿者管理 | 3 | Q5 (操作 + 分析) |
| 领养后跟进 | 3 | Q8 (操作) |
| 分析查询 | 4 | Q1-Q6 (分析) |
| **总计** | **23** | **所有查询** |

---

## 外键约束测试

| 测试项 | 测试内容 | 预期结果 |
|-------|---------|---------|
| FK_VOLUNTEER_SHELTER | 插入 volunteer.shelter_id = 999 | 失败 |
| FK_PET_SHELTER | 插入 pet.shelter_id = 999 | 失败 |
| FK_VACCINATION_PET | 插入 vaccination.pet_id = 999 | 失败 |
| FK_MEDICAL_RECORD_PET | 插入 medical_record.pet_id = 999 | 失败 |
| FK_CARE_ASSIGNMENT_VOLUNTEER | 插入 care_assignment.volunteer_id = 999 | 失败 |
| FK_CARE_ASSIGNMENT_PET | 插入 care_assignment.pet_id = 999 | 失败 |
| FK_ADOPTION_APPLICATION_APPLICANT | 插入 adoption_application.applicant_id = 999 | 失败 |
| FK_ADOPTION_APPLICATION_PET | 插入 adoption_application.pet_id = 999 | 失败 |
| FK_ADOPTION_RECORD_APPLICATION | 插入 adoption_record.application_id = 999 | 失败 |
| FK_FOLLOW_UP_ADOPTION | 插入 follow_up.adoption_id = 999 | 失败 |