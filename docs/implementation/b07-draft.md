# B07 草稿：结构化要求与证据 ID

版本：草稿；日期：2026-11-03。规则优先六类抽取、人工确认与工作台清单已具备；可选 **LLM 精抽**（硅基流动）用于补全／纠正低置信字段，仍强制证据可定位。

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
| 规则抽取 | `backend/bid_agent/services/requirement_extract.py`（`b07-rule-v2`） |
| LLM 精抽 | `backend/bid_agent/services/requirement_llm_refine.py`（`b07-hybrid-v1`） |
| 仓储 | `backend/bid_agent/repositories/requirements.py` |
| 表结构 | `requirement_items`（platform migration v2） |
| API | `backend/bid_agent/api/routes/requirements.py` |

## 3. API

```http
POST /api/v1/document-versions/{version_id}/requirements/extract
Content-Type: application/json

{
  "job_id": "job_...",
  "use_llm": true,
  "llm_vendor": "siliconflow",
  "llm_model": "Qwen3-8B (轻量)"
}
```

`use_llm=false`（默认）只跑规则。精抽需 `.env` 中 `LLM_API_KEY`；模型／地址默认硅基流动 `Qwen/Qwen3-8B`。

```http
GET /api/v1/document-versions/{version_id}/requirements?category=overview
GET /api/v1/document-versions/{version_id}/requirements?extractor_version=all
```

列表默认取该版本**最近一次**抽取器版本（`updated_at` 最新）；历史版本仍保留。已 `confirmed` 的条目不会被同版本重抽覆盖。传 `extractor_version=all` 可看全部。

```http
POST /api/v1/requirements/{item_id}/review
Content-Type: application/json

{"review_status": "confirmed", "normalized_value": "可选修正值"}
```

重新抽取只会替换同一 `extractor_version` 下仍为 `draft` 的条目，**不会覆盖**已 `confirmed` 的人工确认。

## 4. 已知限制

- LLM 精抽仅覆盖概览补强与部分条款候选；技术参数表／复杂评分仍噪声大。
- LLM 输出无原文证据（quote 找不到）会被丢弃，不落库。
- 证据定位依赖 block 文本包含关系，页码来自解析元数据。
- 章节过碎时，同一类条款可能偏多，需人工筛选确认。

## 5. 样例召回（安阳，2026-11-03）

对已成功解析版本 `dv_ebbbf68f3e8049b78161c121e07b50d8` 跑抽取，对照 [golden/01-anyang…](../samples/golden/01-anyang-zhengwu-yunwei.json)：

| 版本 | 概览必填 | 资格 | 废标 | 备注 |
|---|---|---|---|---|
| `b07-rule-v1`（修复前） | 7/9 | 4/4 | 3/3 | 开标／截标仅标题；联合体无证据 |
| `b07-rule-v2` | **9/9（100%）**，证据 100% | 4/4 | 3/3 | 下一行「时间：」写入时刻；短值用标签线索找证据 |
| `b07-hybrid-v1`（硅基流动 Qwen3-8B，约 84s） | **9/9（100%）**，证据 100% | 4/4 | 3/3 | 与规则同档召回；条款候选有增补但仍与规则池合并约 137 条 |

快照：[golden recall](../samples/golden/01-anyang-zhengwu-yunwei.recall.json)、[hybrid recall](../samples/golden/01-anyang-zhengwu-yunwei.hybrid.recall.json)。  
评测：`python scripts/eval_requirement_recall.py --golden docs/samples/golden/01-anyang-zhengwu-yunwei.json --base-url http://127.0.0.1:8080 --version-id <dv_id>`。

## 6. 工作台（2026-11-03）

文档工作台 `workspace.html` 在解析结果下方增加「要求清单」：

- 文档版本行「要求清单」或查看成功任务后自动加载最近抽取器草稿
- 「抽取／刷新」；可勾选「LLM 精抽（硅基流动）」
- 分类页签；可改 `normalized_value` 后确认／驳回／恢复草稿
- 「跳到原文」按 `section_index`／路径／摘录打开上方章节并高亮

## 7. 下一步

1. 再进入 B08 PostgreSQL 迁移。
2. 技术类草稿降噪（可选）。
3. 精抽改为后台任务，避免同步 HTTP 长时间占用。
