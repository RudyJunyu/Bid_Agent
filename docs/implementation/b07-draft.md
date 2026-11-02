# B07 草稿：结构化要求与证据 ID

版本：草稿；日期：2026-11-03。本轮只交付**规则优先**的六类要求抽取与证据挂接，人工确认 API 已具备；LLM 精抽、冲突检测、工作台 UI 仍属后续。

## 1. 目标

对已成功解析的文档版本，生成可保存的要求清单：

- 六类：`overview` / `qualification` / `rejection` / `commercial` / `technical` / `scoring`
- 每条含 `raw_text`、`normalized_value`、`confidence`、`review_status`、`source_refs`
- `source_refs` 尽量指向解析 `block_id`、章节路径和页码

验收口径（草稿级）：重要概览字段能抽到，且至少一部分条目带有可定位证据。

## 2. 代码落点

| 部分 | 文件 |
|---|---|
| Schema | `backend/bid_agent/schemas/requirements.py` |
| 规则抽取 | `backend/bid_agent/services/requirement_extract.py` |
| 仓储 | `backend/bid_agent/repositories/requirements.py` |
| 表结构 | `requirement_items`（platform migration v2） |
| API | `backend/bid_agent/api/routes/requirements.py` |

## 3. API

```http
POST /api/v1/document-versions/{version_id}/requirements/extract
Content-Type: application/json

{"job_id": "job_..."}   # 可选；缺省用该版本最近成功解析
```

```http
GET /api/v1/document-versions/{version_id}/requirements?category=overview
```

```http
POST /api/v1/requirements/{item_id}/review
Content-Type: application/json

{"review_status": "confirmed", "normalized_value": "可选修正值"}
```

重新抽取只会替换同一 `extractor_version` 下仍为 `draft` 的条目，**不会覆盖**已 `confirmed` 的人工确认。

## 4. 已知限制

- 仅规则／关键词，无 LLM；技术参数表、复杂评分公式召回不完整。
- 证据定位依赖 block 文本包含关系，页码来自解析元数据。
- 尚无前端确认工作台；请用 API 或后续接 UI。
- 章节过碎时，同一类条款可能偏多，需人工筛选确认。

## 5. 下一步

1. 用 `docs/samples` 标注黄金字段，统计概览／资格／废标召回。
2. 对低置信条目接入 LLM 精抽，仍强制 Schema + 证据校验。
3. 工作台增加「要求清单」页：点字段跳转原文。
4. 再进入 B08 PostgreSQL 迁移。
