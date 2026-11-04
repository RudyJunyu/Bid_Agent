# B10 草稿：项目内证据检索与索引版本

版本：2026-11-05。在 SQLite 上先行项目内关键词语料重建与 Recall@K 评测；不宣称向量／混合检索生产就绪。

## 能力

| 能力 | 落点 |
|---|---|
| 索引版本 | `index_versions`（`platform_migrations` v9） |
| 语料 | 要求条目／章节正文／关联企业资产 |
| 检索 | `POST /v1/projects/{id}/search`；必须有项目 ACL |
| 评测 | `POST /v1/projects/{id}/retrieval-eval`；样例见 `docs/samples/retrieval` |
| 重建 | `POST /v1/projects/{id}/indexes/rebuild` |

## 限制

- 语料在内存按项目现算，非持久向量库；`index_versions` 只记元数据与语料统计。
- chunk id 约定：`req:`／`sec:`／`asset:`。
- 跨项目命中必须为空或 403；评测集需人工填 `relevant_ids`。
