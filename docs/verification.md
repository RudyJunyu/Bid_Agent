# 本次改造验证记录

日期：2026-11-02。验证针对当前工作区修改，未提交 Git commit，未发布远程服务。

## 已通过

| 验证 | 结果与范围 |
|---|---|
| Python 3.12 回归测试 | **13 passed**，使用隔离临时 SQLite，关闭真实模型和向量下载 |
| 原接口兼容检查 | 原 25 个业务路由的方法与路径仍出现在 OpenAPI |
| 本地解析 | 动态构造 DOCX 与原生 PDF，上传并检查解析结果 |
| 知识库 | 新建、列表、导出、删除 |
| 项目链路 | 入库、详情、关键词检索、目录、无模型草稿、删除 |
| 输入边界 | 空文件 422、超限 413、服务器本地路径／output_dir 默认拒绝 |
| 配置隔离 | 模型选择不修改进程环境，章节生成参数能传至模型构造器 |
| 健康与 CORS | `/health`、`/ready`，默认不开放任意跨域 |
| Python 静态检查 | Ruff F821／F822／F823／E9 通过；Python 编译检查通过 |
| JavaScript | Web 和 Electron 入口 `node --check` 通过 |
| Compose | `docker compose config --quiet` 通过 |
| 前端容器 | 使用已缓存 DaoCloud Nginx 镜像构建成功，非 root、只读文件系统、cap_drop 条件下 `nginx -t` 通过 |
| 前端 HTTP | 临时容器 `/`、`/app.js`、`/styles.css`、`/healthz` 全部返回 200；测试后已关闭容器 |
| 历史数据完整性 | 6 个 Chroma 文件及原迁移 ZIP 的 Git blob hash 与重构前完全一致 |
| Git 格式 | `git diff --check` 通过 |

测试存在一条 Starlette 关于未来 TestClient 推荐 `httpx2` 的弃用提示，不影响本次 13 项通过结果。当前测试依赖仍使用 httpx。

前端容器验证采用本机缓存镜像：

```text
m.daocloud.io/docker.io/library/nginx@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752
实际 Nginx 版本：1.31.3
验证镜像：bid-agent-web:verify
```

该镜像与默认配置的 `nginx:1.28-alpine` 不同，不能将此验证表述为默认前后端镜像已全部构建成功。

## 构建阻塞与未覆盖部分

默认镜像已按要求切换至 DaoCloud。Docker Hub 和 DaoCloud 的大镜像层下载均持续缓慢；宿主机直连 DaoCloud 时出现 `image-mirror.r2.daocloud.vip` 读取超时，另一 Python 3.12 Bookworm 标签出现 TLS 握手超时。

因此 **默认 Python 3.12 后端镜像尚未完成构建，整套 Compose 的启动、代理联通、卷持久化与重启恢复尚未实测通过**。没有把本机 pytest 成功等同于整套 Docker 上线成功。重复下载／构建任务已停止，避免在后台持续占用资源。

以下内容也未作完成声明：

- 完整版 OCR、Docling、Chroma、Embedding、Reranker：依赖锁文件解析成功，但未安装完整镜像或下载模型验证。
- 真实 LLM／MinerU 调用与输出质量：本次未提供业务凭据，未执行付费外部调用。
- 浏览器全流程交互和 Electron 安装包：已检查语法和页面资源，未进行交互自动化／打包验证。
- 备份／恢复脚本：已编写，未对真实业务数据执行恢复演练。
- CI：工作流已配置，未在远程 GitHub Actions 中执行。
- 正式 DOCX／PDF 导出、权限、后台任务和版本管理：属于后续实施方案。

## 下载恢复后应执行的验证

在项目根目录运行：

```bash
docker compose --progress plain build
docker compose up -d --wait --wait-timeout 120
python scripts/smoke_test.py
docker compose exec web nginx -t
docker compose ps
```

再创建一条专用测试知识记录，重建 API 容器并读取该记录，确认卷持久化；最后删除该测试记录。随后按部署手册进行冷备与独立项目恢复演练。

## 本次发现并修复的具体问题

1. 目录迁移导致的旧 import、脚本入口与路径引用全部更新。
2. 模型选择修改全局环境，改为请求内解析。
3. 章节草稿请求缺少 `enable_deep_thinking`，原异常被捕获后会静默跳过模型，已补字段并覆盖测试。
4. 本地 Word 转换分支使用 `subprocess` 却未导入，已修复；Linux 下明确提示先转 DOCX。
5. SQLite connection context manager 不自动关闭连接，导致 Windows 测试数据库无法释放，已显式关闭。
6. 浏览器默认接口指向本机 8000，改为当前站点 `/api`。
7. Nginx 在只读容器中试图创建默认 FastCGI／uWSGI／SCGI 临时目录，已全部改到 `/tmp` 并重新验证。
