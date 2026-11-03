# 存储库指南

面向 AI 与协作者的仓库约定。人类用户优先读 [README](README.md)；完整方案与验收见 [docs](docs/)。

## 协作与交付

- 默认使用简体中文；代码标识符、命令和必要技术术语保留原文。
- 修改前检查工作区及相关调用方，保留已有改动；优先复用已有实现，避免平行造轮子。
- 提交采用英文类型前缀加中文目的，如 `feat: 文档工作台支持取消解析任务`；使用 `feat`、`fix`、`docs`、`chore`、`refactor`、`test`，一次提交聚焦一个主题。
- 交付区分已修改、已验证、跳过、阻断与用户暂缓；历史截图、冒烟通过不能代替当前业务验收。涉及界面时附截图或复现步骤。

## 项目结构与当前状态

```text
Bid_Agent/
├── frontend/
│   ├── web/                     # 浏览器静态页：工作台 + 原分析工具
│   │   ├── workspace.html/.js   # 默认首页：原件、要求、闸门、审查、导出
│   │   ├── index.html/app.js    # 旧分析／知识库／标书工具
│   │   ├── api.js               # 同源 /api 客户端
│   │   └── legacy-session.js    # 认证会话与 CSRF 共享
│   └── desktop/                 # 可选 Electron 外壳（无本地拉起 Python）
├── backend/bid_agent/
│   ├── main.py                  # FastAPI 入口、建表／迁移钩子、路由挂载
│   ├── worker.py                # Celery 解析任务消费者
│   ├── dispatcher.py            # outbox 发布与失联任务恢复
│   ├── cli.py                   # 可选 Plan-and-Solve 命令行入口
│   ├── api/routes/              # auth／workspace／requirements／stages／bids／reviews…
│   ├── repositories/            # workspace／jobs／requirements／stages／bids／compliance
│   ├── schemas/                 # Pydantic：请求模型与 ParsedDocument
│   ├── services/                # 解析、要求抽取、目录、审查、导出、分析编排
│   ├── compliance/              # 可插拔合规检查（规则优先）
│   ├── parsing/                 # PDF／DOCX／策略与图像元数据
│   ├── analysis/                # 规则、Prompt、专项抽取与清洗
│   ├── rag/                     # FTS／可选 Chroma 与章节召回
│   ├── generation/              # 目录与章节草稿
│   ├── review/                  # 旧内容辅助审查
│   ├── infrastructure/          # database／object_store／llm／docx_export／mineru
│   ├── core/                    # settings／security／identity／model_config
│   └── agents/                  # Plan-and-Solve 示例（未接入主业务链路）
├── deploy/
│   ├── docker/                  # backend／frontend Dockerfile（DaoCloud 基础镜像）
│   └── nginx/                   # 同源反代、上传与流式超时
├── requirements/                # base／full／dev 输入与锁文件
├── scripts/                     # start、smoke、backup、reindex
├── tests/                       # pytest 回归与旧路由契约夹具
├── docs/                        # 方案、架构、实施、部署、验证、样例招标文件
├── archives/                    # 历史迁移包说明（非开发基线）
├── storage/                     # 本地／Compose 数据卷挂载点（gitignore）
├── compose.yaml                 # web／api／worker／dispatcher／redis
├── pyproject.toml
└── .env.example
```

**当前版本 0.3.0。** 已落地 B01–B06：Repository 拆分、原件对象存储与不可覆盖版本、任务表／outbox／Redis／Celery、统一 `ParsedDocument`、登录与项目角色骨架、文档工作台。另有 B07 要求清单草案，以及阶段闸门／评分对齐目录／合规审查／DOCX 导出骨架（SQLite `platform_migrations` v3，见 [bid-pipeline](docs/implementation/bid-pipeline.md)）。主业务调用链：

`api/routes` → `services` → `repositories`／`infrastructure` → SQLite WAL 与本地对象目录；解析任务另经 `dispatcher` → Redis → `worker` → `services.document_parser` → `parsing`。

旧分析长请求仍走 `services/analysis_workflow` 与 `api/routes/documents`，尚未全部迁入任务队列。PostgreSQL／Alembic、S3、企业资产、PDF 转换 Worker 等仍属 B08–B16，见 [完整实施方案](docs/project-completion-plan.md)。

Compose 五服务：仅 `web`（Nginx）发布宿主机端口；`api`／`worker`／`dispatcher` 共用后端镜像与 `bid-data` 卷；`redis` 独立卷。默认 API 单进程、Worker 并发 1；不能用网络文件系统共享 SQLite 做多主机写扩容。

## 开发前阅读

| 任务 | 必须先读 |
| --- | --- |
| 产品范围、阶段与验收 | [完整实施方案](docs/project-completion-plan.md) |
| B01–B06 数据模型、状态机、权限与接口边界 | [实施说明](docs/implementation/b01-b06.md) |
| B07 结构化要求与证据（草稿） | [B07 草稿](docs/implementation/b07-draft.md) |
| 闸门／目录／审查／DOCX 闭环骨架 | [bid-pipeline](docs/implementation/bid-pipeline.md) |
| 本轮增量改动说明（给接手伙伴） | [改动说明](docs/改动说明.md) |
| 模块职责、新旧链路与技术债 | [架构梳理](docs/architecture/overview.md) |
| Compose、认证、备份恢复与排错 | [Docker 部署手册](docs/deployment/docker.md) |
| 本轮已验证与未覆盖项 | [验证记录](docs/verification.md) |
| 解析评测样例招标文件 | [docs/samples](docs/samples/README.md) |
| 结构化入库目标表设计（后续） | [库表设计](docs/database/schema-design.md) |

人类快速上手见根 [README](README.md)。`docs/archive/` 与根 `archives/` 为历史资料，不作为开发基线。

## 编码约定

- 后续代码和工具同时兼容 Windows 与 macOS／Linux；平台差异集中在 `scripts/start.ps1`、`scripts/start.sh`、`start.bat`。路径不硬编码盘符或个人目录；文本读写显式 UTF-8；Shell 脚本保持 LF（见 `.gitattributes`）。不得复制 `.venv`、模型缓存或二进制运行时跨系统复用。
- Python 四空格；前端现有静态 JS 保持现有风格，不擅自引入未约定的打包框架。包名与模块 `snake_case`；Pydantic／路由模型集中在 `schemas`。
- **新业务禁止在路由里写 SQL。** 路由只做参数、鉴权与 HTTP 适配；持久化进 `repositories`；编排进 `services`；外部 SDK（LLM／MinerU／对象存储）留在 `infrastructure`。
- 解析产出必须落入统一 `ParsedDocument` 校验路径；原件写入走 `object_store`（流式、SHA-256、原子替换），元数据与任务／outbox 同事务约束见实施说明。
- `agents/plan_and_solve` 仅为示例，不得宣称已接入主投标闭环；不要为“智能体”名义引入未评审的通用 Agent 框架。显式状态机与数据库任务记录仍是权威状态。
- 同步处理错误响应、日志脱敏、项目权限隔离；修复须带能复现原问题的回归。重构先固定契约，再改目录与导入。

## 构建与验证

从仓库根目录执行。推荐 Python **3.12**（声明支持 3.11／3.12）。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS／Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements/dev.in
python -m pip install --no-deps -e .
```

| 修改范围 | 检查命令或验收要求 |
| --- | --- |
| 后端／仓储／服务 | `python -m pytest -q`；`ruff check backend tests scripts` |
| 前端静态脚本 | `node --check frontend/web/*.js frontend/desktop/*.js` |
| Compose 配置 | `docker compose config --quiet` |
| 整栈冒烟 | `docker compose up -d --build --wait`，再 `curl` `/healthz` 与 `/api/ready`，或 `python scripts/smoke_test.py` |
| 仅 API 本地调试 | 须同时配置一致的 DB／原件目录／Redis，并启动 worker＋dispatcher；只跑 uvicorn **不会**消费解析队列 |
| 纯文档 | 检查链接与事实；不宣称完成业务回归 |

CI（`.github/workflows/ci.yml`）覆盖 pytest、ruff、前端 `node --check`、Compose 构建与健康检查。完整队列／恢复类验证以 [verification](docs/verification.md) 为准；本地未提交的额外脚本不得当作仓库默认可复现步骤。

## 安全边界

- 密钥与模型凭据仅留 `.env`／部署密钥库；提交排除 `.env`、证书、`storage/**`（除 README）、上传原件与模型缓存。
- 开启 `BID_AUTH_ENABLED` 后须配置强管理员密码；旧分析／知识库接口限管理员。面向非本机绑定前配置 HTTPS。
- 原件下载必须鉴权；对象路径不可直接公网暴露。Worker 解析前复核内容哈希。
- 禁止在未授权情况下对生产数据卷执行 `down -v`、全局 prune 或不可逆删除；备份用 `scripts/backup_data.py` 或部署手册流程。
- 样例招标文件（`docs/samples`）仅供解析评测，不用于真实投标。

## 文档维护

- 结构、目录、服务边界变化同步 [架构](docs/architecture/overview.md)、README「项目结构」与本文件。
- 范围、阶段、验收变化同步 [完整实施方案](docs/project-completion-plan.md)；B01–B06 边界变化同步 [实施说明](docs/implementation/b01-b06.md)；B07 及相关草稿边界同步 [B07 草稿](docs/implementation/b07-draft.md)。
- 部署与运维步骤变化同步 [Docker 手册](docs/deployment/docker.md)；重要验证结果追加 [verification](docs/verification.md)。
- **持续维护 [改动说明](docs/改动说明.md)**：凡影响行为、API、数据模型、解析策略、默认配置或验收方式的交付，必须在同一次提交中追加一条变更记录。每条记录标题必须带 **日期和时间**，格式 `YYYY-MM-DD HH:MM`，时区 **UTC+8（Asia/Shanghai）**，例如 `## 2026-11-03 01:22`；新记录插在「变更记录」区最上方。正文至少含：动机、文件清单、行为前后对比、验证方式、已知限制、给接手人的注意点。纯错别字或无损重构可在当次记录写“改动说明：已检查，无需更新”。该文件面向后续开发伙伴，不能用口头说明或仅 PR 描述代替。
- 新增、重命名、下线文档时同步 [文档导航](docs/文档导航.md) 与本文件「开发前阅读」。
- `docs/` 说明文档优先中文文件名；本文件、`compose.yaml`、契约 JSON、代码目录 README 保留固定英文名。
- 单次变更达到 6 个文件（不含构建产物与 `storage`）时必须复核受影响文档；上述改动说明等持续维护要求**不受** 6 文件门槛限制。
- 交付时列出已更新文档与验证缺口；检查本指南，长期约定变化时同步更新本文件，否则注明“AGENTS：已检查，无需更新”。
