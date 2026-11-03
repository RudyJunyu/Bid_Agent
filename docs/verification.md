# 0.3.0 验证记录

日期：2026-11-02。以下结果在本次 B01–B06 改造提交前取得，未发布远程服务。Docker 联调使用独立 Compose 项目 `bid-agent-verify`、本机端口 18089 和独立命名卷，样本均为合成文档。本轮新增及修改的测试文件、冒烟和流程验证脚本按要求保留在本地，不包含在本次提交中；34 项结果对应本地完整测试集。

## 已通过的检查

| 验证 | 结果与实际范围 |
|---|---|
| Python 3.12 回归 | **34 passed**；隔离临时 SQLite，不访问用户数据、不调用付费模型 |
| 旧接口兼容 | 原 25 条业务路由仍在 OpenAPI；原项目、知识库、检索、生成回归通过 |
| 新原件与版本 | 字节级下载、SHA-256、重复内容复用、v1／v2 不覆盖、跨项目关系拒绝 |
| 文件边界 | 无效格式、空文件、超限、存储路径穿越、原件缺失与哈希不一致 |
| 任务事务 | 幂等提交、同键不同请求冲突、outbox 插入失败整体回滚 |
| 执行与事件 | 本地 DOCX／PDF 统一结构、重复投递不重复执行、游标补读、终态 SSE |
| 故障单元测试 | 旧租约不能覆盖新尝试、取消／重试、重试上限、超时错误脱敏、发布租约过期和消息丢失补偿 |
| 权限单元测试 | owner／viewer／陌生用户，下载／任务／事件权限，CSRF、旧接口不可绕过、退出后 401 |
| Docker 构建 | 默认 Python 3.12 后端镜像成功；固定 DaoCloud Nginx 摘要前端镜像成功 |
| Compose 运行 | api／web／redis／worker／dispatcher **全部 healthy**；非 root、只读根文件系统、命名卷条件下运行 |
| HTTP 与 Nginx | 首页、新旧 JS／CSS、健康检查、认证状态、OpenAPI 通过；`nginx -t` 通过 |
| 真实队列 | `verify_workflow.py` 通过 HTTP → SQLite outbox → Redis → Celery → 结果落库，幂等返回同一任务，单次尝试完成 |
| 容器重建 | 对五个服务执行 `--force-recreate` 后，原件哈希、版本记录、解析结果 ID 与正文仍一致 |
| Redis 故障 | 停止测试 Redis 后提交解析仍返回 202，状态 queued；启动 Redis 后自动完成，无需重新提交 |
| Worker 故障 | 12,000 段合成 DOCX 进入 running 后 SIGKILL Worker；启动后等待 60 秒租约恢复，**attempts=2**，有 recovered 事件、完整末段和唯一最终结果 |
| 浏览器完整流程 | Chrome／Playwright 操作创建项目、上传 v1／v2、下载比对哈希、刷新恢复历史、查看结果、Markdown 下载、旧工具交接；无 JS 页面异常 |
| 窄屏 | 390×844 视口下项目／版本正常显示，无横向溢出 |
| Docker 登录页面 | 认证启动创建管理员；管理员登录、创建用户／项目成员、viewer 禁用写操作和旧工具、退出后 401 |
| 冷备份 | `backup_data.py` 停止 web／dispatcher／worker／api，复制后恢复此前服务；逐文件 SHA-256、SQLite integrity_check、2 个版本及 2 条结果验证通过 |
| 静态检查 | Ruff 配置项 F821／F822／F823／E9、所有 Web／Electron JS 的 `node --check`、Compose 配置与 `git diff --check` 通过 |

pytest 有一条 Starlette 关于未来 TestClient 推荐 `httpx2` 的弃用提示，不影响 34 项通过结果。当前测试依赖仍用 httpx。

## 构建记录与镜像

最终默认前端镜像已经统一更新为以下 DaoCloud 固定摘要，实际 Nginx **1.31.3**：

```text
m.daocloud.io/docker.io/library/nginx@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752
```

后端基于 `m.daocloud.io/docker.io/library/python:3.12-slim`，本次构建解析到：

```text
sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
```

Redis 使用 `m.daocloud.io/docker.io/library/redis:7-alpine`。应用镜像为 `bid-agent-api:local` 与 `bid-agent-web:local`；API／Worker／Dispatcher 共用后端镜像，避免重复构建同一标签。

最初 Nginx 1.28 镜像层持续停滞，已停止该构建并切换为已有 DaoCloud 固定摘要。Python 包索引曾短暂返回无可用版本，之后又遇到读取超时；确认依赖存在后，为构建加入 pip 缓存挂载、120 秒超时与 5 次重试，后端成功构建。上述失败属于排错记录，不是最终部署仍被阻塞。

## README 页面与终端

- `docs/images/workspace-overview.png`：1440×1100 的真实工作台截图，包含演示项目、版本列表、已完成任务。
- `docs/images/workspace-result.png`：实际解析结果区域截图，展开各章节；并非设计效果图。
- 页面截图使用“智慧园区运维服务采购”合成 DOCX：第一版部署周期 30 日，第二版 45 日；下载与结果验证使用同一文件。
- Windows／Linux 启动脚本增加 READY 横幅，只有 Compose 健康等待成功后打印，地址从实际端口映射读取。Windows 实际运行成功，Linux 脚本通过容器内 `sh -n` 检查；`.gitattributes` 保持 shell 脚本 LF 行尾。
- 本机 8080 端口无法绑定，已将本机 `.env` 的 `BID_HTTP_PORT` 设为 18089。最终默认项目 `bid-agent` 的五个服务全部 healthy，启动脚本退出码 0，READY 横幅显示 `http://127.0.0.1:18089/`。README 摘录此次输出，省略动态列；新部署模板仍默认 8080。
- 独立 `bid-agent-verify` 验证容器已关闭，测试数据卷保留；当前运行的是默认 `bid-agent` 项目。截图为前述独立测试环境中的合成示例，默认项目不会自动导入这些演示数据。

## 本地验收命令记录

以下保留本轮实际使用的命令，其中测试和验证脚本的本轮改动未提交。新检出版本请按实施说明使用页面及容器健康检查验收，不能直接据此复现全部 34 项本地测试。

```bash
python -m pytest -q
ruff check backend tests scripts
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
python scripts/smoke_test.py
python scripts/verify_workflow.py
docker compose exec web nginx -t
docker compose ps
```

容器重建持久化：

```bash
python scripts/verify_workflow.py --keep-project --state-file .work/workflow-state.json
docker compose up -d --force-recreate --wait --wait-timeout 180
python scripts/verify_workflow.py --verify-state .work/workflow-state.json
```

本地 `verify_workflow.py` 仅依赖 Python 标准库。启用认证时通过环境变量 `BID_VERIFY_USERNAME`／`BID_VERIFY_PASSWORD` 使用测试管理员。默认脚本会删除自己的项目记录；验证状态文件时需保留该项目。故障注入仅在独立测试部署执行，不能直接对正在使用的业务服务停机。

## B07 样例召回（2026-11-03）

在默认 Compose（`127.0.0.1:8080`，五服务 healthy）上，对既有项目「安阳政务信息化运维」已成功解析版本 `dv_ebbbf68f3e8049b78161c121e07b50d8`（job `job_abbd92d378944561984dc74d3c5931f4`，本地 pdfplumber）执行：

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/v1/document-versions/dv_ebbbf68f3e8049b78161c121e07b50d8/requirements/extract" \
  -H 'Content-Type: application/json' -d '{}'
python scripts/eval_requirement_recall.py \
  --golden docs/samples/golden/01-anyang-zhengwu-yunwei.json \
  --base-url http://127.0.0.1:8080 \
  --version-id dv_ebbbf68f3e8049b78161c121e07b50d8
```

结果快照见 [samples/golden/01-anyang-zhengwu-yunwei.recall.json](samples/golden/01-anyang-zhengwu-yunwei.recall.json)（`b07-rule-v2`）：

| 指标 | 结果 |
|---|---|
| 草稿条数 | 137（overview 14／qualification 22／rejection 16／technical 60／scoring 15／commercial 10） |
| 概览必填召回 | **9/9（100%）**；命中条证据率 **100%** |
| 资格条款召回 | **4/4（100%）**（「信用中国」跨 qualification＋rejection 检索） |
| 废标条款召回 | **3/3（100%）** |
| v2 修复点 | 下一行「时间：」写入开标／截标时刻；联合体等短值用标签线索挂证据；列表默认按当前 `EXTRACTOR_VERSION` 过滤 |
| 仍存缺口 | technical 草稿噪声偏大；可选「合同期限」字段不稳定；仅安阳单样本 |

这是**单样本规则抽取草稿验收**，不能替代方案中 ≥98% 资格／废标目标或多样本业务签字。

### 工作台要求清单 UI（同日）

重建 `bid-agent-web:local` 后，在 `http://127.0.0.1:8080/workspace.html`：

- 安阳项目已解析版本出现「要求清单」按钮；查看成功任务后自动加载 137 条（概览默认 14）。
- 「抽取／刷新」、六类页签、跳原文、确认／驳回可用；实测将「项目名称」确认为 `confirmed`（API 复核）。
- 截图：`docs/images/workspace-requirements.png`。

### B07 LLM 精抽联调（2026-11-03 14:50）

配置硅基流动 `LLM_API_KEY` 后，对同一安阳版本执行 `use_llm=true`（模型 `Qwen/Qwen3-8B`）：

- 约 **84s** 完成；落库 `extractor_version=b07-hybrid-v1`，137 条。
- 黄金召回：概览 9/9、资格 4/4、废标 3/3（与 rule-v2 同档）；快照见 `docs/samples/golden/01-anyang-zhengwu-yunwei.hybrid.recall.json`。
- 实现注意：避免 SiliconFlow `json_schema` 长挂起，精抽改为普通 chat JSON；`LLM_TIMEOUT=300`。

### 投标闭环骨架（2026-11-03 23:53）

单元／API（隔离临时库，无外部模型）：

- `test_json_repair`：fence／think 标签／正文内嵌 JSON。
- `test_score_coverage`：评分矩阵行与目录覆盖率。
- `test_bid_pipeline`：未开闸门拒建目录；开 requirements → 保存 `bid_version` → 审查 findings → 开 check → 导出 DOCX（PK 头）并鉴权下载；MinerU 状态只读。

未覆盖：真实业务样例端到端截图、LibreOffice PDF、LLM 审查实调、工作台浏览器回归。

## 尚未验证／未实施

- 真实 MinerU／LLM 服务调用、OCR／扫描件质量、复杂跨页表格、真实招标业务验收。本轮没有使用业务密钥或付费外部调用。
- full 镜像的 OCR／Docling／Chroma／Embedding／Reranker 推理及模型下载；本轮实测 runtime 镜像。
- 章节级 ParsedDocument 不等于精确页坐标或逐表格结构。当前 DOCX 解析会保留表格文字，但原有解析器可能展开／重复表格内容，不能据此认定复杂表格结构已验收。
- 冷备副本通过哈希与完整性检查；尚未把该副本导入新卷进行完整恢复／切流演练，生产恢复目标和容量指标未验证。
- PostgreSQL／Alembic、S3、PDF 转换 Worker、完整标书协同编辑仍属后续。同步 DOCX 导出与阶段闸门已有 API 回归，不等于排版黄金样本与业务签字验收。B07 规则／hybrid 精抽、要求清单 UI 与安阳单样本召回已有记录，不等于方案级字段验收完成。旧分析长请求与 LLM 精抽均未迁入任务队列（精抽仍为同步请求，约 1–2 分钟）。
- 账号找回／重置、成员撤销、统一业务审计、单点登录、企业级多租户与生产安全加固尚未完成。
- Electron 安装包与远程 GitHub Actions 未执行。CI 保留仓库原有回归、静态检查、Compose 启动和直接 HTTP 健康检查，不依赖本轮未提交的验证脚本。
