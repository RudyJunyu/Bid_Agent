# 投标闭环骨架：闸门／目录／审查／导出

版本：2026-11-04。在 0.3.0（B01–B07 草案）之上，工作台补齐「要求确认 → 目录 → 审查 → DOCX」闭环骨架；数据仍在 SQLite `platform_migrations` v3。B08 PostgreSQL、企业资产、PDF Worker 等仍后置。

## 1. 能力与落点

| 能力 | 落点 | 说明 |
|---|---|---|
| JSON 修复／`collect_json` | `infrastructure/json_repair.py`、`llm_client.py` | 可选 `LLM_FALLBACK_MODELS`、token 汇总 |
| 阶段闸门 | `project_stages` + `repositories/stages.py` + `/v1/projects/{id}/stages` | requirements→outline→generate→check→export |
| 评分对齐目录 | `services/score_coverage.py`、`services/bid_outline.py`、`bid_versions`／`bid_sections` | 硬依赖 requirements 闸门 |
| 合规检查包 | `compliance/` + `compliance_runs`／`compliance_findings` | 规则优先；可选 LLM 废标辅助；表名避开旧分析库 `review_findings` |
| DOCX 导出 | `infrastructure/docx_export.py`、`services/bid_export.py`、`export_artifacts` | 硬依赖 check 闸门；同步路径 |
| MinerU 状态 | `/v1/integrations/mineru` | 只读／探活；PUT 仅进程内覆盖，不写 `.env` |

## 2. 本轮后置

- B08 PostgreSQL／Alembic、B09 企业资产、B10 检索评测
- LibreOffice PDF 转换 Worker、复杂 Word 排版美化
- 更全量的 LLM 检查项与查重向量层
- 前端框架重写、通用 Agent 编排

B11–B15 产品行为可先在 SQLite 验收；正式迁库仍以 B08 为准。

## 3. 工作台流程

1. 解析 → 抽取／确认要求 → **通过 requirements 闸门**
2. 「生成并保存目录」→ 查看评分覆盖率
3. 「运行审查」→ 处理 findings → **通过 check 闸门**
4. 「导出 DOCX」→ 鉴权下载

## 4. 验证

见 [verification](../verification.md) 与 `tests/test_bid_pipeline.py`、`tests/test_json_repair.py`、`tests/test_score_coverage.py`。
