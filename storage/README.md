# 运行数据

本目录只用于本机开发和旧数据迁移，内容不进入镜像。

- `data/bid_agent.db`：本机 SQLite 数据库。
- `chroma/`：从旧根目录 `.chroma/` 原样迁移的历史向量索引。
- Docker 使用独立命名卷 `bid-agent_bid-data`，**不会自动导入本目录**。
- 迁移时优先复制旧 SQLite 数据库，再根据新版本重新构建向量索引；只有向量文件不能恢复完整项目。
- 详见 `docs/deployment/docker.md` 的备份、恢复和迁移步骤。
