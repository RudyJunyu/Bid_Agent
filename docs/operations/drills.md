# 运维演练（B16 草稿）

## 恢复演练

1. `python scripts/backup_data.py --output-dir backups`
2. `python scripts/drill_recovery.py --backup-dir backups/<stamp> --expect-db`
3. 在**非生产** Compose 项目中恢复 storage 卷后，检查 `/healthz` 与主流程。

本草稿只验证备份清单哈希；完整切流／RTO 需单独环境签字。

## 容量探测

```bash
python scripts/drill_capacity.py --base-url http://127.0.0.1:8080 --rounds 20
```

仅探测网关健康接口延迟，不代表解析队列或 LLM 容量。

## 迁库准备（B08）

```bash
python scripts/sqlite_inventory.py --output storage/reports/sqlite-inventory.json
```

见 [b08-postgres](../implementation/b08-postgres.md)。
