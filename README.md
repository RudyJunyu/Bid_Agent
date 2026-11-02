# Bid Agent · 招投标智能工作台

基于 FastAPI 的招标文件、原件版本和后台解析工作台，保留知识库、条款分析、检索及标书草稿工具。默认通过 **Docker Compose + 浏览器** 使用，Electron 为可选外壳。

**当前版本 0.3.0，已落地 B01–B06**：数据仓储拆分、授权原件下载、不可覆盖文档版本、澄清附件关系、Redis/Celery 后台解析、任务恢复、统一 ParsedDocument 和页面闭环。后续 B07–B16 包括字段级证据、PostgreSQL、企业资产、标书版本与正式 DOCX／PDF 导出，详见[完整方案](docs/project-completion-plan.md)。

## 一键启动

要求 Docker Desktop（Linux 容器模式）或 Docker Engine，以及 Docker Compose **2.24+**。宿主机无需安装 Python、Node 或模型运行环境。

Windows PowerShell：

```powershell
powershell -File scripts/start.ps1
```

也可以双击 `run.bat`。Linux／macOS：

```bash
sh scripts/start.sh
```

脚本仅在 `.env` 不存在时复制模板，构建镜像并等待全部服务健康后显示访问地址。首次构建需要下载依赖；后续 Windows 可用 `powershell -File scripts/start.ps1 -NoBuild`。

手动启动等价操作（已有 `.env` 时不要覆盖）：

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 180
```

Windows 的复制命令为 `Copy-Item .env.example .env`。默认打开 **http://127.0.0.1:8080/**，API 文档为 **http://127.0.0.1:8080/api/docs**。若 `.env` 配置了其他 `BID_HTTP_PORT`，以启动终端打印的网址为准；本次本机已设置为 **http://127.0.0.1:18089/**。

镜像默认使用 **DaoCloud**：Python 3.12 slim、Redis 7 Alpine、Nginx 1.31.3（固定 SHA-256 摘要）。可以通过 `.env` 中的 `PYTHON_IMAGE`、`REDIS_IMAGE`、`NGINX_IMAGE` 替换。Nginx 1.28 下载停滞后已统一切换到实际验证的固定镜像，详见[验证记录](docs/verification.md)。

## 启动成功后的终端

下面是本次本机成功启动输出的节选（省略镜像、命令和创建时间列）。由于本机 8080 端口不可绑定，实际使用 18089；新部署默认仍为 8080。只有 `docker compose up --wait` 成功后才会打印 **READY**，脚本中的网址会随实际端口变化。

```text
SERVICE       STATUS                    PORTS
api           Up ... (healthy)          8000/tcp
dispatcher    Up ... (healthy)          8000/tcp
redis         Up ... (healthy)          6379/tcp
web           Up ... (healthy)          127.0.0.1:18089->8080/tcp
worker        Up ... (healthy)          8000/tcp

============================================================
  BID AGENT | READY
  web / api / worker / dispatcher / redis: healthy
  Workspace : http://127.0.0.1:18089/
  API docs  : http://127.0.0.1:18089/api/docs
  Next: Create project -> Upload original -> View parse result
  Logs: docker compose logs -f --tail 100 api worker dispatcher
============================================================
```

出现 `unhealthy` 或启动错误时，先查看 `docker compose logs --tail 100 api worker dispatcher redis web`。仅网页可访问不能证明后台解析正常，应同时检查五个服务状态。

## 实际页面预览

以下截图来自本项目真实 Docker 服务与 Chrome 页面，使用**合成演示招标文件**，没有使用真实客户数据。新安装的项目列表为空，创建项目并上传原件后会出现版本与任务。

**文档工作台：项目、原件上传、历史版本和后台任务。**

![实际文档工作台，展示演示项目及原件历史版本](docs/images/workspace-overview.png)

**解析结果：章节正文、来源版本、提示信息和 Markdown 下载。**

![真实解析结果页面，展示章节、技术要求和商务要求](docs/images/workspace-result.png)

## 第一次使用

1. 左侧输入名称，点击“创建项目”。
2. 选择 PDF／DOCX 原件。离线体验时明确选择“本地 PDF 文本”或“本地 DOCX”；自动策略可能选择需要凭据的 MinerU。
3. 点击“保存原件并解析”。页面返回任务编号，关闭或刷新页面不会中断后台任务。
4. 任务成功后点击“查看结果”，核对正文并下载 Markdown；“下载原件”返回上传时的原始字节。
5. 上传修订稿时，在“保存到”中选择已有文档，系统新增 v2，不覆盖 v1。同一文档重复上传相同内容会复用版本。
6. 上传澄清或附件时设置文档类型及“关联原文档”。失败任务可重试，排队任务可取消；运行中取消需要等待当前解析步骤结束。
7. 管理员可点击“进入原工具核对”继续使用原分析界面。进一步分析入库仍走旧流程，字段级证据与新版本的整合属于 B07。

本地 PDF／DOCX 解析不需要模型密钥。智能分析需要 `.env` 中的 `LLM_API_KEY`、`LLM_MODEL_ID`、`LLM_BASE_URL`；远程 MinerU 需要 `MINERU_API_TOKEN`。默认基础镜像关闭本地向量模型，使用 OCR／Docling／Chroma 时按[部署手册](docs/deployment/docker.md)启用 full 镜像。

## 团队登录与数据保存

默认仅绑定 `127.0.0.1`，`BID_AUTH_ENABLED=false` 是本机单用户管理员模式。团队使用时设置 `BID_AUTH_ENABLED=true`、首次管理员用户名和至少 12 字符的密码；HTTPS 下设置 `BID_COOKIE_SECURE=true`。成员有 owner／editor／viewer 权限，原件、任务、事件和结果均检查项目授权；旧分析与知识库接口仅管理员可用。[账号创建和成员分配说明](docs/implementation/b01-b06.md#8-权限与接口)。

`bid-agent_bid-data` 保存 SQLite、原件 objects 和可选 Chroma；`bid-agent_queue-data` 保存 Redis AOF；`bid-agent_model-cache` 保存模型缓存。`docker compose down` 保留这些卷。**需要数据时不要执行 `docker compose down -v`。** 宿主 `storage/` 与 Docker 卷是不同目录。

当前是单机 SQLite 部署，默认 API 单进程、Worker 并发 1。精确页坐标、扫描件质量评测、S3 后端、账户生命周期、全业务审计及生产容量验证仍有待后续阶段完成。

## 目录与文档

```text
Bid_Agent/
├── backend/bid_agent/
│   ├── main.py                 # FastAPI 入口与初始化
│   ├── api/routes/             # 认证、工作台、旧业务接口
│   ├── repositories/           # 项目、知识、版本、权限、任务、outbox
│   ├── schemas/                # 输入模型和 ParsedDocument
│   ├── services/               # 后台解析与原分析流程
│   ├── parsing/                # 文档解析器与策略
│   ├── analysis/               # 规则、Prompt 与专项抽取
│   ├── rag/                    # 关键词／向量检索
│   ├── generation/             # 目录与章节草稿
│   ├── review/                 # 辅助审查
│   ├── infrastructure/         # 原件存储、数据库、外部服务
│   ├── core/                   # 配置、身份、会话
│   ├── worker.py               # Celery 消费者
│   └── dispatcher.py           # outbox 发布与失联任务恢复
├── frontend/web/               # 文档工作台与旧分析工具
├── frontend/desktop/           # 可选 Electron 外壳
├── deploy/                     # Dockerfile 与 Nginx 配置
├── requirements/               # 基础／完整依赖与锁文件
├── scripts/                    # 启动、验收、备份、索引维护
├── tests/                      # 隔离数据库回归测试
├── docs/                       # 实施、部署、架构、验证与实拍截图
├── storage/                    # 本地开发数据，非 Docker 命名卷
├── compose.yaml                # web/api/redis/worker/dispatcher
└── .env.example
```

| 文档 | 内容 |
|---|---|
| [B01–B06 实施与验收](docs/implementation/b01-b06.md) | 表结构、状态机、权限、接口、恢复机制和限制 |
| [完整项目实施方案](docs/project-completion-plan.md) | 最终目标、B07–B16、阶段依赖与验收 |
| [架构梳理](docs/architecture/overview.md) | 新旧链路、目录职责与技术债 |
| [Docker 部署手册](docs/deployment/docker.md) | 配置、认证、迁移、备份恢复、排错 |
| [验证记录](docs/verification.md) | 实际执行结果、故障演练和未验证范围 |

## 日常操作与开发

```bash
docker compose ps
docker compose logs -f --tail 100 api worker dispatcher
docker compose stop
docker compose up -d --wait --wait-timeout 180
```

宿主安装 Python 3.11+ 后可运行无第三方依赖的备份脚本：

```bash
python scripts/backup_data.py
```

备份脚本会短暂停止所有业务写入进程，详见部署手册。本轮新增及修改的测试文件、冒烟与流程验证脚本按要求保留在本地，不包含在本次提交中；实际执行结果记录在验证文档。

本地开发推荐 Python 3.12：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate；Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements/dev.in
python -m pip install --no-deps -e .
python -m pytest -q
ruff check backend tests scripts
```

仅运行 uvicorn 不会处理后台任务；本地 API／Worker／Dispatcher 与 Redis 的调试方式见部署手册。Electron 在 Docker 启动后于 `frontend/desktop` 执行 `npm ci`、`npm start`，通过 `BID_WEB_URL` 指定网页地址。
