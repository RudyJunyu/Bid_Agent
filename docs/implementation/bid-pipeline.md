# 投标闭环骨架：闸门／目录／章节／矩阵／资产／检索／成章／审查／导出

版本：2026-11-05。在 0.3.0（B01–B07 草案）之上，工作台补齐「要求确认 → 企业资产 → 目录 → 章节／证据成章 → 响应矩阵 → 审查审批 → 模板化 DOCX／可选 PDF」闭环骨架；数据仍在 SQLite `platform_migrations` v9。B08 PostgreSQL 仅有迁库骨架，正式切流未做。

## 1. 能力与落点

| 能力 | 落点 | 说明 |
|---|---|---|
| 阶段闸门 | `services/stage_gates.py` | check 受高风险未闭环拦截 |
| 评分对齐目录／章节 | `bid_outline`／`bid_sections` | 目录自动 outline；正文就地保存 |
| 响应矩阵（B13） | `response_matrix`／`requirement_responses` | 可提示可用／过期企业资产 |
| 企业资产（B09） | `enterprise_assets` 等 | 过期不可用于生成 |
| 证据检索（B10） | `evidence_search`／`index_versions` | 项目内关键词；Recall@K |
| 证据成章（B12） | `evidence_section` | 规则拼装；无依据标【待补充】；暂关 LLM |
| 审查审批（B15） | `compliance_*`／`audit_logs` | 高风险必填备注；任务批准 |
| 导出模板（B14） | `export_templates`／`docx_export`／`pdf_convert` | full／technical／commercial／dark_technical；页码／目录／附录；可选 LibreOffice PDF |
| 运维演练（B16） | `scripts/drill_*`、`docs/operations/drills.md` | 备份哈希／健康延迟探测，非生产 RTO 签字 |
| MinerU 状态 | `/v1/integrations/mineru` | 只读／探活 |

## 2. 本轮后置

- B08 正式 PostgreSQL 切流与 Alembic 生产迁移
- 向量／混合检索持久索引、独立 PDF Worker、自定义 `.dotx`
- 黄金样本人工视觉签字；前端框架重写

## 3. 工作台流程

1. 解析 → 抽取／确认要求 → 企业资产
2. 生成目录 → 编辑或「证据约束生成」章节 → 重建响应矩阵
3. （可选）重建索引／检索评测
4. 审查 → 批准 → 通过 check
5. 选择导出模板 → 导出 DOCX（可选转 PDF）

## 4. 检索与成章 API

```http
POST /api/v1/projects/{id}/indexes/rebuild
POST /api/v1/projects/{id}/search
{"query":"质量管理体系认证","limit":10}
POST /api/v1/projects/{id}/retrieval-eval
{"k":10,"cases":[{"query":"...","relevant_ids":["req:..."]}]}
POST /api/v1/bid-sections/{id}/generate-from-evidence
{"overwrite":true,"mark_generate_gate":true,"use_llm":false}
```

## 5. 验证

见 [verification](../verification.md) 与 `tests/test_retrieval_and_evidence.py`、`tests/test_export_templates.py`、`tests/test_bid_pipeline.py`。
