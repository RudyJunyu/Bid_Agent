# 检索评测样例（B10）

将评测用例做成 `{"query","relevant_ids"}` 列表，`relevant_ids` 使用检索返回的稳定 chunk id：

- `req:<requirement_item_id>`
- `sec:<bid_section_id>`
- `asset:<enterprise_asset_id>`

示例：

```bash
curl -s -X POST "$BASE/api/v1/projects/$PROJECT_ID/retrieval-eval" \
  -H 'Content-Type: application/json' \
  -d @docs/samples/retrieval/example-cases.json
```

先 `POST /indexes/rebuild`，再跑评测。跨项目检索必须 403／空结果。
