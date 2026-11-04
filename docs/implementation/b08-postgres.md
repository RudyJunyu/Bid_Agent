# B08 草稿：PostgreSQL／Alembic 迁库骨架

版本：2026-11-05。正式迁库尚未执行；本文件固定目标顺序与验收门槛，避免在 SQLite 业务主链未稳时强切数据库。

## 1. 目标

- 以 PostgreSQL 作为团队版权威库；SQLite 保留为开发／单机路径。
- Alembic 管理 schema；禁止手工改生产表结构。
- 迁移可回滚：旧卷冷备 + 校验报告归零或逐项批准。

## 2. 建议依赖（未写入默认 base 锁）

仅在启用迁库环境时安装：

```bash
python -m pip install "sqlalchemy>=2,<3" "alembic>=1.13,<2" "psycopg[binary]>=3,<4"
```

环境变量：

```bash
DATABASE_URL=postgresql+psycopg://bid:bid@127.0.0.1:5432/bid_agent
```

未配置 `DATABASE_URL` 时，应用继续使用现有 SQLite（`BID_DB_PATH`）。

## 3. 迁移顺序

1. `python scripts/sqlite_inventory.py --output storage/reports/sqlite-inventory.json`
2. 建立空 PostgreSQL，应用首版 schema（见 `deploy/postgres/schema_v1.sql`）。
3. 只读导出 SQLite → JSONL／CSV；保留旧业务 ID。
4. 按父表到子表导入；重建 FTS／向量索引（不复制索引文件）。
5. 校验行数、抽样证据、权限隔离；差异报告归零。
6. 停写 → 最终增量 → 切流；旧系统只读窗口。

## 4. 首批必须迁的平台表

`users`／`sessions`／`project_members`／`projects`／`documents`／`document_versions`／`jobs`／`job_events`／`outbox_events`／`parsed_documents`／`requirement_items`／`project_stages`／`bid_versions`／`bid_sections`／`requirement_responses`／`enterprise_assets`／`enterprise_asset_versions`／`project_asset_links`／`compliance_*`／`export_artifacts`／`audit_logs`／`index_versions`／`platform_migrations`

## 5. 验收

- [ ] inventory 报告生成
- [ ] schema_v1 可在空库执行
- [ ] 抽样项目端到端：登录 → 原件 → 要求 → 导出
- [ ] 回滚演练：恢复 SQLite 冷备可继续服务

## 6. 非目标（本草稿不做）

- 不在默认 Compose 中强制启动 PostgreSQL
- 不在本次切换生产写路径
- 不宣称 B08 完成
