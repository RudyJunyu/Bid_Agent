# Docker 部署与运维手册

当前版本是单机、单 API 实例部署。`web` 提供页面和反向代理，`api` 处理业务，SQLite 和可选 Chroma 位于命名卷。没有 Redis／PostgreSQL 服务，团队版的迁移路线见完整实施方案。

## 1. 环境与镜像

- Windows：Docker Desktop，启用 WSL2 与 Linux containers。
- Linux：Docker Engine + Docker Compose 插件。
- Compose 版本至少 2.24，使用了可选 `env_file`。
- 默认基础镜像按本次要求改用 DaoCloud：
  - `m.daocloud.io/docker.io/library/python:3.12-slim`
  - `m.daocloud.io/docker.io/library/nginx:1.28-alpine`
- 初次构建需要访问镜像站和 PyPI；完整版本地模型首次使用还要访问模型仓库。
- 基础版建议从 4 GB 内存起验证；完整 OCR／向量依赖建议 16 GB 以上并预留较多磁盘，实际用量以样本测试为准。

先检查：

```bash
docker version
docker compose version
docker info
```

镜像站 `/v2/` 返回 401 和 Bearer challenge 是正常的 registry 认证流程，不表示镜像无法使用。下载慢时查看具体层进度，避免反复启动多个相同构建。

## 2. 初始化配置与启动

在仓库根目录操作。

Windows PowerShell：

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose --progress plain build
docker compose up -d --wait --wait-timeout 120
```

Linux／macOS：

```bash
cp .env.example .env
docker compose config --quiet
docker compose --progress plain build
docker compose up -d --wait --wait-timeout 120
```

不要覆盖已有 `.env`；已有配置仅补新增字段。Windows 可直接执行 `scripts/start.ps1` 或 `run.bat`，脚本只在文件不存在时复制模板。Linux 可执行 `sh scripts/start.sh`。

访问：

- 页面：`http://127.0.0.1:8080`
- API 存活：`http://127.0.0.1:8080/api/health`
- 数据库就绪：`http://127.0.0.1:8080/api/ready`
- 接口文档：`http://127.0.0.1:8080/api/docs`
- OpenAPI：`http://127.0.0.1:8080/api/openapi.json`

Nginx 自身 `/healthz` 只证明网页服务存活；检查后端必须使用 `/api/ready`。探针不调用付费模型，API Key 留空不会导致容器无法启动。

## 3. 配置项

| 变量 | 默认／示例 | 含义 |
|---|---|---|
| `BID_BIND_HOST` | `127.0.0.1` | 仅本机访问；内网地址需结合访问控制配置 |
| `BID_HTTP_PORT` | `8080` | 唯一对外 HTTP 端口 |
| `BID_IMAGE_TARGET` | `runtime` | 基础镜像；`full` 包含本地 AI 依赖 |
| `BID_IMAGE_TAG` | `local` | 应用镜像标签，发布时改成明确版本 |
| `PYTHON_IMAGE` | DaoCloud Python 3.12 | 可替换为私有仓库／固定 digest |
| `NGINX_IMAGE` | DaoCloud Nginx 1.28 | 可替换为私有仓库／固定 digest |
| `LLM_API_KEY` | 空 | 模型供应商密钥 |
| `LLM_MODEL_ID` | 空 | 供应商实际模型 ID，不能仅填界面展示名 |
| `LLM_BASE_URL` | 空 | 兼容接口服务地址 |
| `LLM_TIMEOUT` | `180` | 模型超时秒数 |
| `LLM_MAX_CONCURRENCY` | `2` | 同步分析并发参数 |
| `LLM_STREAM_MAX_CONCURRENCY` | `4` | 流式模块并发参数 |
| `MINERU_API_TOKEN` | 空 | 远程 MinerU 解析凭据 |
| `BID_MAX_UPLOAD_MB` | `50` | 单个文件上限，单位 MiB |
| `BID_ALLOW_SERVER_PATHS` | `false` | 是否允许服务器文件路径／output_dir |
| `BID_CORS_ORIGINS` | 空 | 同源无需配置；跨域填完整 origin，逗号分隔 |
| `BID_VECTOR_STORE_ENABLED` | `false` | 是否建立／查询 Chroma 向量 |
| `RERANKER_ENABLED` | `false` | 是否使用本地重排模型 |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | 本地向量或已有远程适配，见代码支持值 |
| `EMBEDDING_MODEL_ID` | `BAAI/bge-large-zh-v1.5` | 向量模型；变更模型时重建索引 |
| `RERANKER_MODEL_ID` | `BAAI/bge-reranker-v2-m3` | 重排模型 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型仓库镜像，与 Docker 镜像站不同 |

资格预筛、结构化输出、MinerU 分页参数继续保留于 `.env.example`。模型界面选项会覆盖本次请求的模型选择，但不会改变其他请求的全局配置；已有供应商选择表只实现了 SiliconFlow 映射，其他供应商通过默认环境配置或后续适配接入。

Compose 强制设置容器内 `BID_DB_PATH=/app/storage/data/bid_agent.db`、`CHROMA_PERSIST_DIR=/app/storage/chroma`、`HF_HOME=/app/.cache/huggingface`、`BID_ROOT_PATH=/api`。不要把宿主机 Windows 路径写入容器环境。

Nginx 请求体上限是 52 MiB，为默认 50 MiB 文件预留 multipart 开销。调整文件上限时同时修改 Nginx 的 `client_max_body_size` 和后端变量，并检查 `/tmp` 空间。

修改环境后执行 `docker compose up -d --force-recreate --wait`。单纯 `restart` 不会更新容器创建时的环境变量。

## 4. 基础版与完整版

| 能力 | runtime | full |
|---|---|---|
| 原生 PDF／DOCX 本地解析 | 支持 | 支持 |
| 远程 MinerU／LLM | 配置密钥后支持 | 配置密钥后支持 |
| 知识库、SQLite、FTS | 支持 | 支持 |
| 本地 OCR／Tesseract | 不含相关依赖 | 包含依赖，真实样本需验证 |
| Docling | 不含 | 包含，可能首次下载模型 |
| Chroma、本地 Embedding／Reranker | 不含 | 包含，需启用和下载模型 |

基础版没有本地向量模型时仍可使用关键词检索。使用本地 AI 的配置示例：

```dotenv
BID_IMAGE_TARGET=full
BID_VECTOR_STORE_ENABLED=true
RERANKER_ENABLED=true
```

然后：

```bash
docker compose build api
docker compose up -d --wait --wait-timeout 180
docker compose exec api python scripts/reindex.py
```

完整锁文件可能引入较大的 Torch／模型生态依赖；本次默认镜像不安装这些包。CPU／GPU 的专用镜像优化应单独验证，当前配置未指定 NVIDIA runtime 或 GPU 设备。不要把“full 依赖解析成功”当作本地模型推理已经验证。

旧二进制 `.doc` 的本地转换原先依赖 Windows Word COM，在 Linux 容器中不支持。请先保存为 `.docx`；本项目没有在镜像中隐式安装 Word 或 LibreOffice。

## 5. 持久化与原数据迁移

默认 Compose 项目名 `bid-agent`，对应：

| 卷 | 容器路径 | 内容 |
|---|---|---|
| `bid-agent_bid-data` | `/app/storage` | SQLite、Chroma |
| `bid-agent_model-cache` | `/app/.cache` | 下载的模型缓存 |
| tmpfs | `/tmp` | 临时解析文件，容器重建后消失 |

容器以非 root 用户运行，API UID/GID 为 10001。初始化命名卷时 Docker 复制镜像目录权限；手动导入文件后需检查属主。

原 `.chroma` 已原样移动为宿主机 `storage/chroma`，并排除出新构建上下文。原 ZIP 移到 `archives/`。不会自动把这些内容导入 Docker，避免把过期索引误认成当前数据。

迁移步骤：

1. 停止旧程序，备份旧 `data/bid_agent.db` 及其可能存在的 `-wal`／`-shm`。确认数据库干净关闭，必要时用 SQLite backup API 生成一致性快照。
2. 记录 SHA-256、项目数量、知识库条目数量。没有旧 SQLite 时不能从 Chroma 文件恢复完整业务库。
3. 首次创建新容器和卷，然后停止业务服务。
4. 将旧数据库复制进新 API 数据目录；**只在目标卷为空或已完成备份时进行覆盖**。
5. 修复导入文件的 UID/GID，启动服务，核对数量与抽样内容。
6. 使用 full 版本重建向量；若复制旧 Chroma，先备份并验证版本兼容，旧索引可能由不同版本创建。

PowerShell 示例（源路径替换为已核对的备份）：

```powershell
docker compose up -d --wait
docker compose stop web api
docker compose cp .\backups\legacy\bid_agent.db api:/app/storage/data/bid_agent.db
docker compose run --rm --no-deps --user 0 api chown -R 10001:10001 /app/storage
docker compose up -d --wait
```

不要同时运行旧进程和新容器访问同一个 SQLite 文件。不要把未验证的 Chroma 历史 pickle／索引从不可信来源加载到服务。

## 6. 备份与恢复

本次提供 `scripts/backup_data.py`，需要宿主机 Python 3.11+，不需要安装第三方包：

```bash
python scripts/backup_data.py
```

脚本识别当前项目运行中的 web／api，停止写入，复制 `/app/storage`，生成 SHA-256 清单，并恢复此前运行的服务。默认输出 `backups/UTC时间/`。备份期间服务短暂不可用，必须在可接受窗口执行。

备份不包含 `.env` 和模型缓存。密钥另行保管；模型缓存可以重新下载，业务数据必须异地保存。脚本失败时不把不完整目录视作有效备份。

恢复建议先使用一个**新 Compose 项目和新卷**演练，避免覆盖当前数据。PowerShell 示例：

```powershell
$env:BID_HTTP_PORT = '18080'
docker compose -p bid-agent-restore create
# 将下面目录替换成一次完成且校验过 manifest 的备份。
docker compose -p bid-agent-restore cp .\backups\20261102T080000Z\storage\. api:/app/storage/
docker compose -p bid-agent-restore run --rm --no-deps --user 0 api chown -R 10001:10001 /app/storage
docker compose -p bid-agent-restore up -d --wait
python scripts/smoke_test.py --base-url http://127.0.0.1:18080
Remove-Item Env:BID_HTTP_PORT
```

恢复后检查数据库 `PRAGMA integrity_check`、项目／知识库数量、关键条款、向量检索、导出流程。模型缓存不恢复时向量功能可能重新下载模型。只有演练通过后才计划正式恢复切换。

`docker compose down` 删除容器和网络但保留卷；`docker compose down -v` 会删除卷，不能作为日常重启命令。

## 7. 升级与回滚

1. 运行备份并验证完整性。
2. 保存当前提交号、环境模板版本及镜像 ID／digest。
3. 在测试项目名／端口下构建并跑回归。
4. 设置明确的 `BID_IMAGE_TAG`，执行 build 和 up。
5. 检查 health、ready、项目列表、知识库和一份样本解析。
6. 回滚时使用上一镜像；涉及数据库结构变化则按迁移文档恢复对应备份。

当前建表仍在应用启动时执行，尚无 Alembic 版本迁移。因此这一版不支持未经检查的数据库结构降级，也不应部署多个 API 实例同时初始化同一数据库。

## 8. 排错与验证

```bash
docker compose ps
docker compose logs --tail 100 api web
docker compose exec api python -c "from bid_agent.core.settings import DB_PATH; print(DB_PATH)"
docker compose exec web nginx -t
python scripts/smoke_test.py
```

| 现象 | 检查与处理 |
|---|---|
| Docker 引擎连接失败 | 启动 Docker Desktop，确认 Linux containers 与正确 context |
| 镜像层下载很慢 | 使用本次 DaoCloud 默认地址，检查 Docker 引擎的代理／网络；宿主机可访问不等于引擎可下载 |
| 端口被占用 | `.env` 修改 `BID_HTTP_PORT` 后重新创建 web |
| web 502 | 查看 API 状态和日志；确认两个服务同 Compose 网络，检查 `/ready` |
| 健康但模型调用失败 | health 不测密钥；核对模型 ID、URL、配额和供应商错误 |
| 容器里无法连接宿主模型 | Docker Desktop 使用 `host.docker.internal`，不要填容器自身的 `127.0.0.1` |
| 数据库只读／Permission denied | 检查命名卷权限和导入文件的 UID/GID 10001 |
| 上传 413 | 文件上限／Nginx 上限需一起检查 |
| 解析过程中无进度 | 检查代理缓冲和模型状态；当前仍存在请求内执行的长任务限制 |
| 重建容器后数据看不到 | 检查 Compose 项目名是否改变、卷是否相同；宿主 storage 与命名卷不同 |
| full 找不到模型／离线失败 | 模型缓存是否下载，HF_ENDPOINT 是否可用，磁盘是否足够 |
| .doc 解析失败 | 先转换为 .docx，本地 Word COM 不支持 Linux |

生产发布前还需完成认证、项目隔离、请求限流、原件持久化、任务恢复和真实样本验收。当前回环地址默认适用于本机使用和受控测试。
