# Bid Agent · 招投标智能工作台

基于 FastAPI 的招标文件解析、条款抽取、知识库、证据检索与标书草稿工具。默认通过 **Docker Compose + 浏览器**运行；Electron 保留为连接同一网页的可选桌面外壳。

本次已完成目录重组、API 拆分和容器部署基础。当前属于单实例原型，完整的任务恢复、权限、附件管理、标书版本与 Word/PDF 成品导出仍需开发，具体见实施方案。

## 先阅读哪些文件

| 文档                                           | 内容                                                               |
| ---------------------------------------------- | ------------------------------------------------------------------ |
| [完整实施方案](docs/project-completion-plan.md) | 功能差距、目标架构、数据模型、接口规划、任务拆解、排期、测试和验收 |
| [架构梳理](docs/architecture/overview.md)       | 当前真实链路、目录职责、模块映射、依赖边界和技术债                 |
| [Docker 部署手册](docs/deployment/docker.md)    | 安装、配置、运行、数据迁移、备份恢复、升级、排错                   |
| [验证记录](docs/verification.md)                | 本次实际执行的验证与未覆盖范围                                     |
| [数据库设计](docs/database/schema-design.md)    | 原有数据库设计，设计字段与实际落库字段需结合代码核对               |

## Docker 快速启动

要求 Docker Engine / Docker Desktop Linux 容器模式，Docker Compose **2.24 或以上**。无需在宿主机安装 Python、Node、OCR 或模型运行环境。

```powershell
Copy-Item .env.example .env
docker compose up -d --build --wait --wait-timeout 120
```

Linux / macOS：

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 120
```

打开 **http://127.0.0.1:8080**。Windows 也可以双击 `run.bat`，或运行 `powershell -File scripts/start.ps1`；Linux 可运行 `sh scripts/start.sh`。

无需密钥即可启动并使用本地 PDF／DOCX 解析、知识库、项目查看和关键词检索。完整智能分析需要在 `.env` 填写 `LLM_API_KEY`、`LLM_MODEL_ID`、`LLM_BASE_URL`；使用 MinerU 时填写 `MINERU_API_TOKEN`。默认界面的智能解析策略可能选择 MinerU，离线验证请明确选择 `pdfplumber` 或 `docx2python`。

基础镜像默认关闭本地向量模型，避免首次运行自动下载大模型。需要 OCR、Docling、Chroma、Embedding／Reranker 时，按部署手册将 `BID_IMAGE_TARGET=full` 并启用对应功能。

## 目录

```text
Bid_Agent/
├── backend/bid_agent/
│   ├── main.py                 # 唯一 ASGI 入口
│   ├── api/routes/             # 文档、项目、知识库、健康检查
│   ├── schemas/                # API 请求／响应模型
│   ├── services/               # 分析流程编排
│   ├── parsing/                # PDF／DOCX／图片解析及策略
│   ├── analysis/               # Prompt、规则、抽取、清洗、预筛
│   ├── rag/                    # 候选召回、FTS、Chroma 和重排
│   ├── generation/             # 目录与章节草稿
│   ├── review/                 # 证据核对与内容审查
│   ├── infrastructure/         # SQLite、LLM、MinerU、搜索适配
│   ├── core/                   # 环境配置、模型映射
│   └── agents/                 # 独立 Plan-and-Solve 示例
├── frontend/web/               # 浏览器界面，静态 HTML／CSS／JS
├── frontend/desktop/           # 可选 Electron 网页外壳
├── deploy/docker/              # 后端与前端镜像
├── deploy/nginx/               # 同源 /api 反向代理、流式输出
├── requirements/               # 基础、完整、开发依赖及锁文件
├── scripts/                    # 启动、健康验证、数据备份、索引维护
├── tests/                      # 无外部服务的回归测试
├── docs/                       # 架构、实施、部署、数据库和历史说明
├── storage/                    # 本机数据；Docker 数据另在命名卷
├── archives/                   # 原历史迁移压缩包
├── .github/workflows/ci.yml     # 测试与基础 Docker 启动检查
├── compose.yaml
├── pyproject.toml
└── .env.example
```

## 日常操作

```bash
docker compose ps
docker compose logs --tail 100 api web
docker compose stop
docker compose up -d --wait
python scripts/smoke_test.py
```

`docker compose down` 保留命名卷；不要在需要保留数据时执行 `docker compose down -v`。SQLite 位于 `bid-agent_bid-data` 卷内 `/app/storage/data/bid_agent.db`，模型缓存位于单独卷。

默认只绑定宿主机 `127.0.0.1`，当前应用没有用户认证。团队部署须先完成身份认证和权限控制，或置于已有身份网关之后；公网生产上线要求见实施方案。

## 本机开发

使用 Python 3.11／3.12，推荐与容器一致的 3.12。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate；Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements/dev.in
python -m pip install --no-deps -e .
python -m uvicorn bid_agent.main:app --host 127.0.0.1 --port 8000 --reload
python -m pytest -q
ruff check backend tests scripts
```

本机接口文档为 `http://127.0.0.1:8000/docs`。Docker 下接口文档为 `http://127.0.0.1:8080/api/docs`，OpenAPI JSON 为 `/api/openapi.json`。

可选桌面端：先启动 Docker，再在 `frontend/desktop` 执行 `npm ci`、`npm start`；通过环境变量 `BID_WEB_URL` 指定站点。桌面端不再启动本地 Python。

旧根目录 Python 导入路径已变更，第三方脚本请参考 [模块映射](docs/architecture/module-mapping.json)。原 README 和启动脚本保存在 `docs/archive/`，仅作为历史资料。
