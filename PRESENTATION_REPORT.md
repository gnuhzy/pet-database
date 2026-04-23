# Pet Database Demo & Presentation Report

更新时间：2026-04-23（Asia/Shanghai）

## 1. 项目一句话介绍

`pet-database` 是一个基于 SQLite 的宠物领养中心管理系统，覆盖收容所、宠物、申请、领养、回访、医疗、疫苗、志愿者与照护排班，提供可运行的 Web Demo 与可验证的后端 API。

## 2. 本次现场运行结论（已实际验证）

我已对当前目录的 `pet-database` 做了“启动-请求-停止”的真实演示验证，关键结果如下：

- `GET /api/health` 返回 `200`，并显示数据库路径为当前项目：
  - `"/Users/oier/Downloads/pet/pet/pet-database/pet_database.db"`
- `GET /api/dashboard` 返回 `200`，并成功返回统计数据（节选）：
  - `totalPets=26`
  - `shelterCount=3`
  - `availablePets=9`
  - `pendingApplications=0`
  - `monthlyAdoptions=4`
- `GET /pawtrack_demo.html` 返回 `200`
- 前端页面内容已命中关键演示点：
  - `PawTrack`
  - `Pet (available only)`
  - `GLM-generated SQL`
  - `Asia/Shanghai`
- 安全与协议行为演示：
  - `HEAD /api/health` -> `HTTP/1.0 200 OK`
  - `HEAD /pawtrack_demo.html` -> `HTTP/1.0 200 OK`
  - `GET /.env` -> `404`
  - `GET /pet_database.db` -> `404`

## 3. 课堂分享建议结构（8-12 分钟）

### Slide 1: 背景与目标（1 min）

- 业务目标：让领养流程可追踪、可审计、可演示
- 技术目标：统一 ER 设计、SQLite 落地、可运行 API + 前端

### Slide 2: 系统范围（1 min）

- 数据实体：Shelter、Pet、Applicant、Application、Adoption、FollowUp、Medical、Vaccination、Volunteer、CareAssignment
- 系统能力：查询、流程状态流转、统计分析、LLM 只读查询助手

### Slide 3: 架构图（1 min）

- 前端：`pawtrack_demo.html`
- 后端：`src/web_server.py`
- 数据：`pet_database.db`（CSV 初始化）
- 扩展：`src/llm_sql_assistant.py`（GLM prompt-to-SQL）

### Slide 4: 业务流程（1.5 min）

- 新建申请：`POST /api/applications`
- 审核申请：`PATCH /api/applications/{id}/review`
- 审核通过后生成领养记录，后续可新增回访记录
- 以状态机保证流程一致性

### Slide 5: 数据一致性设计（1.5 min）

- Schema 层：`PK/FK/CHECK/UNIQUE`
- 应用层：跨表/跨行规则校验（如“同一宠物不可并行冲突申请”）
- 审计层：异常检测与活动日志

### Slide 6: 安全与稳健性（1 min）

- 静态资源白名单，阻止敏感文件泄露（`.env`、`.db`）
- JSON 请求体严格校验（UTF-8 + JSON object）
- `HEAD` 支持，便于运维检查
- 统一内部错误处理，避免泄漏堆栈到客户端

### Slide 7: Demo 实录（1.5 min）

- `GET /api/health` 展示服务健康和数据库路径
- `GET /api/dashboard` 展示统计与活动流
- 打开 `pawtrack_demo.html` 展示 Dashboard + 应用模块
- 演示 Assistant 区域 `GLM-generated SQL`（如已配置 `ZAI_API_KEY`）

### Slide 8: 结论与可扩展方向（0.5-1 min）

- 已满足课程展示：可运行、可验证、可解释
- 后续可加：用户鉴权、角色权限、多用户并发、部署与监控

## 4. 现场 Demo 脚本（可照读）

1. “我们先看健康检查，确认系统连接的是当前项目数据库。”
2. “再看 Dashboard，它给出了宠物总量、可领养数和月度领养量等实时统计。”
3. “打开前端后，可以看到主工作台、活动流和申请流程入口。”
4. “系统还提供受控的 LLM SQL 助手，但严格限制只读查询，避免破坏数据。”
5. “最后验证安全边界：`.env` 和数据库文件都不能通过静态路径访问。”

## 5. 演示命令（备用）

在项目根目录 `/Users/oier/Downloads/pet/pet/pet-database`：

```bash
python3 src/web_server.py --host 127.0.0.1 --port 8000
```

浏览器打开：

- `http://127.0.0.1:8000/pawtrack_demo.html`

可选接口验证：

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/dashboard
curl -I http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:8000/pawtrack_demo.html
```

## 6. Q&A 备答（同学常问）

- Q: 为什么选 SQLite？
  - A: 课程场景下部署成本低、可复现强、单文件便于演示与提交。

- Q: LLM 生成 SQL 会不会有风险？
  - A: 后端只允许单条只读 `SELECT/WITH...SELECT`，并做关键词拦截、执行计划校验、只读连接与 authorizer 限制。

- Q: 业务规则放数据库还是代码？
  - A: 领域值和基础约束放 Schema；复杂跨表流程规则放应用层，二者结合。

- Q: 这个系统能直接上线吗？
  - A: 当前定位是教学演示系统，生产化还需鉴权、审计加固、并发治理和部署监控。

## 7. 你做分享时可重点强调的“亮点句”

- “我们不是只做了 ER 图，而是把规则真正执行在数据库和 API 里。”
- “系统演示不是静态页面，所有指标都来自真实 API 和真实 SQLite 数据。”
- “LLM 功能不是裸奔，我们做了只读安全闭环。”
- “这套项目既可展示，也可被自动化测试回归验证。”
