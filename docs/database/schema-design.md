# 招投标智能体数据库表设计

本文档设计的是“解析完成并结构化抽取之后”的数据层。目标不是单纯存文本，而是让招标文件、投标文件、企业知识、历史案例和方案素材可以被检索、审查、复用和生成。

## 设计逻辑

### 1. 先保留原文证据，再做结构化

招投标场景不能只存大模型总结结果。每一条资格要求、评分项、废标项、技术参数和商务条款，都应该能回到原文：

```text
文件 -> 页码 -> 章节 -> 切片 -> 结构化字段 -> 审查/生成引用
```

因此表设计分为两类：

- 原文证据表：保存文件、页码、章节、切片、OCR、图片等来源。
- 业务结构表：保存项目、资格、评分、废标、商务、技术等可操作数据。

### 2. 每张业务表都带溯源字段

业务表统一保留：

- `project_id`
- `document_id`
- `section_id`
- `chunk_id`
- `source_page_start`
- `source_page_end`
- `source_text`
- `confidence`
- `confirmed_status`

这样后续内容审查、人工核对、生成引用时，都能知道“这条信息从哪里来”。

### 3. RAG 不直接拿整篇文档

RAG 推荐使用语义切片：

- 招标项目基本信息按项目切。
- 资格要求按条切。
- 评分项按行切。
- 技术要求按参数点切。
- 商务条款按条款类型切。
- 历史方案素材按可复用段落切。

因此单独设计 `document_chunks` 和 `chunk_embeddings`，不要把所有内容塞进一个字段。

### 4. 企业知识和项目知识分开

项目知识来自招标文件、投标文件、合同、附件；企业知识来自公司信息、资质、人员、财务、业绩、历史案例和方案素材。

项目知识服务“理解这次招标”；企业知识服务“生成这次投标响应”。

---

# 一、基础项目与文件层

## 1. `projects` 项目主表

### 业务作用

一条记录对应一个招投标项目。所有解析结果、资格要求、评分项、商务技术条款、投标文件和审查结果都挂到该项目下。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 项目唯一 ID | 系统生成，不使用项目编号作为主键 | `prj_20260608_001` |
| `project_name` | string | 否 | 项目名称 | 以招标文件中的正式项目名称为准 | `某某平台建设项目` |
| `project_code` | string | 否 | 项目编号 | 包括招标编号、采购编号、项目编号，原文叫什么都统一到此字段 | `ZFCG-2026-001` |
| `project_category` | enum | 否 | 项目类别 | 统一枚举：服务、货物、工程、混合、未知 | `服务` |
| `industry_domain` | string | 否 | 所属领域 | 按业务理解归类，如信息化、物业、设备采购、工程建设 | `信息化` |
| `buyer_name` | string | 否 | 招标人 / 采购人 | 采购主体，统一叫 buyer | `某某局` |
| `agency_name` | string | 否 | 招标代理机构 | 没有代理机构则为空 | `某某招标代理有限公司` |
| `budget_amount` | decimal | 否 | 预算金额 | 只存数字，不带单位 | `1200000.00` |
| `budget_currency` | string | 否 | 币种 | 默认 CNY | `CNY` |
| `max_price_amount` | decimal | 否 | 最高限价 | 只存数字；没有则为空 | `1180000.00` |
| `package_no` | string | 否 | 包号 / 标包 | 多包项目保存当前包号 | `包1` |
| `service_period` | string | 否 | 服务年限 / 履约期限 | 原文表达保留 | `自合同签订之日起三年` |
| `bid_deadline` | datetime | 否 | 投标截止时间 | 尽量标准化；无法解析则为空，原文放 `timeline_items` | `2026-07-01 09:30:00` |
| `bid_open_time` | datetime | 否 | 开标时间 | 同上 | `2026-07-01 09:30:00` |
| `is_sme_reserved` | boolean | 否 | 是否专门面向中小企业 | 是 / 否 / 未知转成 true / false / null | `true` |
| `is_blind_bid` | boolean | 否 | 是否暗标 | 是 / 否 / 未知转成 true / false / null | `false` |
| `status` | enum | 是 | 项目状态 | 解析中、待核对、已核对、生成中、已归档 | `待核对` |
| `created_at` | datetime | 是 | 创建时间 | 系统时间 | `2026-06-08 10:00:00` |
| `updated_at` | datetime | 是 | 更新时间 | 系统时间 | `2026-06-08 10:30:00` |

---

## 2. `source_documents` 文件主表

### 业务作用

保存项目下所有原始文件，包括招标文件、投标文件、合同、附件、澄清文件、图片等。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 文件唯一 ID | 系统生成 | `doc_001` |
| `project_id` | string | 是 | 所属项目 ID | 关联 `projects.id` | `prj_20260608_001` |
| `document_type` | enum | 是 | 文件类型 | 招标文件、投标文件、合同、附件、澄清、图片、其他 | `招标文件` |
| `file_name` | string | 是 | 文件名 | 原始上传文件名 | `招标文件.pdf` |
| `file_ext` | string | 是 | 扩展名 | 小写，无点或带点均可统一 | `pdf` |
| `file_path` | string | 否 | 本地文件路径 | 不建议上传 GitHub；只本地保存 | `C:\...\招标文件.pdf` |
| `file_hash` | string | 否 | 文件哈希 | 用于去重和版本校验 | `sha256:...` |
| `file_size_bytes` | integer | 否 | 文件大小 | 字节 | `5342211` |
| `parse_method` | string | 否 | 实际解析方式 | auto 推荐后的真实方法 | `pdfplumber` |
| `parse_status` | enum | 是 | 解析状态 | 待解析、解析成功、解析失败、部分成功 | `解析成功` |
| `parse_quality_score` | integer | 否 | 解析质量分 | 0-100，来自质量报告 | `82` |
| `page_count` | integer | 否 | 页数 | PDF / Word 转页后页数 | `126` |
| `has_images` | boolean | 否 | 是否含图片 | 预检或解析结果判断 | `true` |
| `has_tables` | boolean | 否 | 是否含表格 | 预检或解析结果判断 | `true` |
| `created_at` | datetime | 是 | 上传时间 | 系统时间 | `2026-06-08 10:05:00` |

---

## 3. `document_sections` 文档章节表

### 业务作用

保存解析后的标题层级和章节内容。它是业务抽取和切片的上游。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 章节 ID | 系统生成 | `sec_001` |
| `document_id` | string | 是 | 文件 ID | 关联 `source_documents.id` | `doc_001` |
| `project_id` | string | 是 | 项目 ID | 冗余方便查询 | `prj_20260608_001` |
| `section_index` | integer | 是 | 章节顺序 | 从 1 开始 | `12` |
| `parent_section_id` | string | 否 | 父章节 ID | 用于标题层级 | `sec_006` |
| `title` | string | 否 | 章节标题 | 尽量保留原文标题 | `第三章 采购需求` |
| `level` | integer | 否 | 标题层级 | 1-6；无法识别则为空 | `2` |
| `page_start` | integer | 否 | 起始页 | 文档页码，不是 PDF 物理页也要注明口径 | `15` |
| `page_end` | integer | 否 | 结束页 | 同上 | `19` |
| `markdown` | text | 是 | Markdown 内容 | 标题 + 正文 + 表格 | `## 采购需求...` |
| `plain_text` | text | 否 | 纯文本内容 | 去掉 Markdown 表格符号后的文本 | `采购需求...` |
| `section_type` | enum | 否 | 章节类型 | 项目概况、商务、技术、资格、评分、合同、附件、未知 | `技术` |

---

## 4. `document_chunks` RAG 切片表

### 业务作用

保存用于检索、向量化和生成引用的最小语义单元。它不是简单按长度切，而是尽量按业务语义切。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 切片 ID | 系统生成 | `chk_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_20260608_001` |
| `document_id` | string | 是 | 文件 ID | 来源文件 | `doc_001` |
| `section_id` | string | 否 | 章节 ID | 来源章节 | `sec_012` |
| `chunk_index` | integer | 是 | 切片顺序 | 文件内或章节内顺序 | `3` |
| `chunk_type` | enum | 是 | 切片类型 | 段落、表格行、资格条款、评分项、废标项、技术参数、商务条款、图片 OCR | `评分项` |
| `module` | enum | 否 | 所属模块 | 投标人须知、商务内容、技术要求、资格审查、评分要求、图片解析 | `评分要求` |
| `title_path` | string | 否 | 标题路径 | 用 `>` 表示层级 | `评标办法 > 技术评分` |
| `content` | text | 是 | 切片正文 | 用于检索和引用的正文 | `实施方案完整性，最高 10 分...` |
| `content_markdown` | text | 否 | Markdown 正文 | 保留表格行格式 | `| 实施方案 | ... | 10 |` |
| `page_start` | integer | 否 | 起始页 | 原文页码 | `52` |
| `page_end` | integer | 否 | 结束页 | 原文页码 | `52` |
| `source_text` | text | 否 | 原文片段 | 证据片段，建议不超过 2000 字 | `原文...` |
| `tags` | json | 否 | 标签 | 行业、风险、条款类型等 | `["技术评分","高分项"]` |
| `metadata` | json | 否 | 检索元数据 | 可扩展字段 | `{"score":10,"risk":"high"}` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 5. `chunk_embeddings` 向量索引表

### 业务作用

保存切片的向量信息。也可以不直接存数据库，而是存到向量库；本表用于记录索引状态和追踪。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 向量记录 ID | 系统生成 | `emb_001` |
| `chunk_id` | string | 是 | 切片 ID | 关联 `document_chunks.id` | `chk_001` |
| `embedding_model` | string | 是 | 向量模型 | 记录模型名和版本 | `BAAI/bge-m3` |
| `embedding_dim` | integer | 是 | 向量维度 | 与模型一致 | `1024` |
| `vector_store` | string | 是 | 向量库存储位置 | chroma、faiss、milvus、pgvector 等 | `chroma` |
| `vector_id` | string | 是 | 向量库 ID | 外部向量库中的 ID | `chk_001` |
| `indexed_at` | datetime | 是 | 建索引时间 | 系统时间 | `2026-06-08 11:00:00` |

---

# 二、结构化抽取层

## 6. `extraction_runs` 抽取任务表

### 业务作用

记录每次结构化抽取任务。用于追踪模型、提示词版本、耗时、成功失败、结果版本。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 抽取任务 ID | 系统生成 | `run_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_20260608_001` |
| `document_id` | string | 否 | 文件 ID | 可为空，表示对编辑后内容重跑 | `doc_001` |
| `run_type` | enum | 是 | 任务类型 | 初次抽取、重新分析、内容审查、深度复核 | `初次抽取` |
| `llm_vendor` | string | 否 | 模型厂商 | 如 siliconflow、openai、moonshot | `siliconflow` |
| `llm_model` | string | 否 | 模型名称 | UI 名称或真实模型 ID | `Qwen3-8B` |
| `prompt_version` | string | 否 | Prompt 版本 | 便于回溯 | `bid_prompt_v2` |
| `input_chunk_ids` | json | 否 | 输入切片 ID | 宽召回后的候选切片 | `["chk_1","chk_2"]` |
| `status` | enum | 是 | 状态 | 成功、失败、部分成功 | `部分成功` |
| `error_message` | text | 否 | 错误信息 | 保存异常摘要 | `Model is private` |
| `started_at` | datetime | 是 | 开始时间 | 系统时间 | `2026-06-08 10:30:00` |
| `finished_at` | datetime | 否 | 结束时间 | 系统时间 | `2026-06-08 10:36:00` |

---

## 7. `project_profile` 项目概览表

### 业务作用

保存“投标人须知 / 项目概览”抽取后的标准字段。通常一个项目一条记录。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 记录 ID | 系统生成 | `profile_001` |
| `project_id` | string | 是 | 项目 ID | 一对一关联项目 | `prj_001` |
| `project_name` | string | 否 | 项目名称 | 与 `projects.project_name` 同口径 | `...` |
| `project_code` | string | 否 | 项目编号 | 与 `projects.project_code` 同口径 | `...` |
| `project_category` | enum | 否 | 项目类别 | 服务、货物、工程、混合、未知 | `服务` |
| `service_period` | string | 否 | 服务年限 | 原文保留 | `三年` |
| `package_no` | string | 否 | 包号 | 原文保留 | `包1` |
| `budget_text` | string | 否 | 预算原文 | 保留金额单位和说明 | `预算金额：120万元` |
| `budget_amount` | decimal | 否 | 预算数值 | 只存数字 | `1200000.00` |
| `buyer_name` | string | 否 | 招标人 / 采购人 | 统一采购主体 | `...` |
| `agency_name` | string | 否 | 代理机构 | 原文机构名称 | `...` |
| `industry_domain` | string | 否 | 所属领域 | 标准化分类 | `信息化` |
| `timeline_summary` | text | 否 | 时间安排摘要 | 原文或结构化摘要 | `获取文件：...；开标：...` |
| `implementation_scope` | text | 否 | 项目实施内容 | 对应“项目要实施的具体内容” | `...` |
| `technical_features` | text | 否 | 主要技术特点 | 原文优先 | `...` |
| `other_key_requirements` | text | 否 | 其他关键要求 | 原文优先 | `...` |
| `is_sme_reserved` | boolean | 否 | 是否面向中小企业 | true / false / null | `true` |
| `is_blind_bid` | boolean | 否 | 是否暗标 | true / false / null | `false` |
| `source_text` | text | 否 | 原文证据 | 关键字段来源原文 | `...` |
| `confidence` | decimal | 否 | 置信度 | 0-1 | `0.86` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 8. `qualification_requirements` 资格审查表

### 业务作用

保存资格性审查、符合性审查和资格证明材料要求。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 资格条款 ID | 系统生成 | `qual_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `review_type` | enum | 是 | 审查类型 | 资格性审查、符合性审查 | `资格性审查` |
| `sequence_no` | string | 否 | 序号 | 保留原文序号 | `1` |
| `requirement_text` | text | 是 | 资格要求 | 尽量原文表达 | `具有独立承担民事责任的能力` |
| `required_materials` | text | 否 | 需提供资料 | 原文证明材料 | `营业执照复印件` |
| `is_mandatory` | boolean | 是 | 是否硬性要求 | 资格审查一般为 true | `true` |
| `risk_level` | enum | 否 | 风险等级 | 高、中、低 | `高` |
| `source_page_start` | integer | 否 | 来源起始页 | 原文页码 | `8` |
| `source_page_end` | integer | 否 | 来源结束页 | 原文页码 | `9` |
| `source_text` | text | 否 | 原文片段 | 可用于审查回溯 | `...` |
| `chunk_id` | string | 否 | 来源切片 | 关联 `document_chunks.id` | `chk_023` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 9. `rejection_items` 废标项表

### 业务作用

保存废标、无效投标、否决投标、重大偏差等硬性风险条款。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 废标项 ID | 系统生成 | `rej_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `sequence_no` | string | 否 | 序号 | 原文序号 | `3` |
| `rejection_item` | text | 是 | 废标项 | 条款名称或摘要 | `未按要求提交投标保证金` |
| `specific_behavior` | text | 是 | 具体表现 | 原文中如何触发废标 | `投标人未在截止时间前缴纳保证金` |
| `risk_level` | enum | 是 | 风险等级 | 高、中、低；废标项默认高 | `高` |
| `related_module` | enum | 否 | 关联模块 | 资格、商务、技术、报价、文件格式、其他 | `商务` |
| `check_method` | text | 否 | 后续审查方式 | 可转为检查清单 | `检查保证金凭证和到账时间` |
| `source_text` | text | 否 | 原文片段 | 原文证据 | `...` |
| `chunk_id` | string | 否 | 来源切片 | 关联切片 | `chk_044` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 10. `business_requirements` 商务要求表

### 业务作用

保存报价、合同、付款、交付、验收、保证金、售后、联合体等商务条款。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 商务条款 ID | 系统生成 | `biz_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `requirement_type` | enum | 是 | 商务要求类型 | 报价、合同、付款、交付、验收、保证金、售后、联合体、分包、其他 | `付款` |
| `item_name` | string | 否 | 条款名称 | 原文或标准化名称 | `付款方式` |
| `requirement_text` | text | 是 | 具体要求 | 尽量原文表达 | `验收合格后支付合同金额的 95%` |
| `amount` | decimal | 否 | 金额 | 若条款含金额则抽取数字 | `50000.00` |
| `ratio` | decimal | 否 | 比例 | 0-1 或百分数统一，建议存 0-1 | `0.95` |
| `deadline_text` | string | 否 | 期限原文 | 复杂期限保留原文 | `合同签订后 10 日内` |
| `is_mandatory` | boolean | 否 | 是否必须响应 | 明确“必须/不得/应”则 true | `true` |
| `source_text` | text | 否 | 原文证据 | 原文片段 | `...` |
| `chunk_id` | string | 否 | 来源切片 | 关联切片 | `chk_050` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 11. `technical_requirements` 技术要求表

### 业务作用

保存技术参数、服务要求、功能要求、验收标准、实施要求等。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 技术条款 ID | 系统生成 | `tech_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `requirement_group` | string | 否 | 技术分组 | 如功能、性能、安全、实施、验收 | `安全要求` |
| `item_name` | string | 否 | 技术条目名称 | 原文标题或参数名 | `系统并发能力` |
| `parameter_name` | string | 否 | 参数名称 | 可为空 | `并发用户数` |
| `parameter_value` | string | 否 | 参数值 | 保留单位 | `不少于 1000 人` |
| `requirement_text` | text | 是 | 具体要求 | 原文优先 | `系统应支持不少于 1000 人同时在线` |
| `acceptance_criteria` | text | 否 | 验收标准 | 没有则为空 | `提供压力测试报告` |
| `is_mandatory` | boolean | 否 | 是否必须响应 | “必须/应/不得/★”等为 true | `true` |
| `importance_level` | enum | 否 | 重要程度 | 高、中、低 | `高` |
| `source_text` | text | 否 | 原文证据 | 原文片段 | `...` |
| `chunk_id` | string | 否 | 来源切片 | 关联切片 | `chk_060` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

## 12. `scoring_items` 评分项表

### 业务作用

保存商务评分、技术评分、价格评分等评分标准。用于投标策略、方案生成和得分自评。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 评分项 ID | 系统生成 | `score_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `score_type` | enum | 是 | 评分类型 | 商务评分、技术评分、价格评分、其他 | `技术评分` |
| `parent_item_id` | string | 否 | 父评分项 | 用于多级评分结构 | `score_000` |
| `item_name` | string | 是 | 评分项 | 原文评分项名称 | `实施方案` |
| `scoring_standard` | text | 是 | 评分标准 | 原文标准，含得分条件 | `方案完整、针对性强得 8-10 分` |
| `score_value` | decimal | 否 | 分值 | 能标准化则存数字 | `10` |
| `score_text` | string | 否 | 分值原文 | 无法标准化或区间分值保留原文 | `8-10 分` |
| `evidence_required` | text | 否 | 证明材料 | 如业绩合同、证书、方案章节 | `提供项目实施方案` |
| `self_assessment` | enum | 否 | 自评状态 | 可得分、风险、缺材料、待评估 | `待评估` |
| `source_text` | text | 否 | 原文证据 | 原文片段 | `...` |
| `chunk_id` | string | 否 | 来源切片 | 关联切片 | `chk_070` |
| `confirmed_status` | enum | 是 | 人工确认状态 | 未确认、已确认、需复核 | `未确认` |

---

# 三、审查层

## 13. `review_findings` 审查发现表

### 业务作用

保存内容审查、合规审查、废标风险检查、大模型深度复核产生的问题。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 审查发现 ID | 系统生成 | `rf_001` |
| `project_id` | string | 是 | 项目 ID | 关联项目 | `prj_001` |
| `review_type` | enum | 是 | 审查类型 | 内容完整性、原文溯源、废标风险、响应偏离、一致性 | `废标风险` |
| `module` | enum | 是 | 所属模块 | 项目概况、商务、技术、资格、评分、图片、其他 | `资格` |
| `risk_level` | enum | 是 | 风险等级 | 高、中、低 | `高` |
| `finding_title` | string | 是 | 问题标题 | 简短描述 | `原文存在废标条款但提取缺失` |
| `finding_detail` | text | 是 | 问题详情 | 说明原因 | `资格审查输出未包含无效投标条款...` |
| `source_text` | text | 否 | 原文证据 | 对应原文片段 | `...` |
| `suggestion` | text | 否 | 处理建议 | 人工核对或补充响应建议 | `补充到废标项表并检查响应文件` |
| `status` | enum | 是 | 处理状态 | 待处理、已确认、已忽略、已修复 | `待处理` |
| `created_by` | enum | 是 | 来源 | 正则、LLM、人工 | `正则` |
| `created_at` | datetime | 是 | 发现时间 | 系统时间 | `2026-06-08 11:20:00` |

---

# 四、企业知识库层

## 14. `companies` 公司信息表

### 业务作用

保存投标主体的基础信息。多公司投标或集团子公司场景下可保存多条。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 公司 ID | 系统生成 | `co_001` |
| `company_name` | string | 是 | 公司全称 | 与营业执照一致 | `某某科技有限公司` |
| `short_name` | string | 否 | 公司简称 | 内部使用 | `某某科技` |
| `credit_code` | string | 否 | 统一社会信用代码 | 营业执照号码 | `9132...` |
| `legal_representative` | string | 否 | 法定代表人 | 营业执照信息 | `张三` |
| `registered_capital` | string | 否 | 注册资本 | 保留原文单位 | `1000万元人民币` |
| `business_scope` | text | 否 | 经营范围 | 营业执照原文 | `...` |
| `address` | string | 否 | 注册地址 | 营业执照原文 | `...` |
| `contact_person` | string | 否 | 联系人 | 投标常用联系人 | `李四` |
| `contact_phone` | string | 否 | 联系电话 | 文本保存，避免前导 0 丢失 | `010-...` |
| `company_profile` | text | 否 | 公司简介 | 可用于商务标 | `...` |
| `status` | enum | 是 | 状态 | 有效、停用 | `有效` |

---

## 15. `company_qualifications` 资质管理表

### 业务作用

保存营业执照、资质证书、认证证书、授权书等。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 资质 ID | 系统生成 | `cq_001` |
| `company_id` | string | 是 | 公司 ID | 关联 `companies.id` | `co_001` |
| `qualification_type` | enum | 是 | 资质类型 | 营业执照、体系认证、行业资质、授权、许可证、其他 | `体系认证` |
| `qualification_name` | string | 是 | 资质名称 | 证书正式名称 | `ISO9001质量管理体系认证` |
| `certificate_no` | string | 否 | 证书编号 | 原文编号 | `CN-...` |
| `issuer` | string | 否 | 发证机构 | 原文机构 | `某认证机构` |
| `issue_date` | date | 否 | 发证日期 | 标准日期 | `2025-01-01` |
| `expire_date` | date | 否 | 到期日期 | 长期有效可为空，备注说明 | `2028-01-01` |
| `valid_status` | enum | 是 | 有效状态 | 有效、临期、过期、待核对 | `有效` |
| `file_path` | string | 否 | 附件路径 | 本地或对象存储路径 | `...` |
| `applicable_scope` | text | 否 | 适用范围 | 哪些项目可用 | `信息化服务类项目` |
| `notes` | text | 否 | 备注 | 使用提示 | `投标时需加盖公章` |

---

## 16. `company_personnel` 人员信息表

### 业务作用

保存可用于投标的项目经理、技术负责人、团队成员和证书履历。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 人员 ID | 系统生成 | `person_001` |
| `company_id` | string | 是 | 公司 ID | 关联公司 | `co_001` |
| `name` | string | 是 | 姓名 | 身份证/证书一致 | `张三` |
| `role` | string | 否 | 常用角色 | 项目经理、技术负责人、实施工程师 | `项目经理` |
| `title` | string | 否 | 职称 | 高级工程师等 | `高级工程师` |
| `certificates` | json | 否 | 证书列表 | 证书名、编号、有效期 | `[{"name":"PMP","expire":"2027-01-01"}]` |
| `education` | string | 否 | 学历 | 原文或标准化 | `本科` |
| `years_experience` | decimal | 否 | 工作年限 | 数字 | `8` |
| `project_experience` | text | 否 | 项目经验 | 可用于技术标 | `...` |
| `file_path` | string | 否 | 证明材料路径 | 简历、证书等 | `...` |
| `availability_status` | enum | 是 | 可用状态 | 可用、占用、停用、待确认 | `可用` |

---

## 17. `financial_records` 财务信息表

### 业务作用

保存审计报告、财务指标、纳税社保、银行资信等投标常用财务材料。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 财务记录 ID | 系统生成 | `fin_001` |
| `company_id` | string | 是 | 公司 ID | 关联公司 | `co_001` |
| `record_type` | enum | 是 | 记录类型 | 审计报告、财务报表、纳税证明、社保证明、银行资信 | `审计报告` |
| `fiscal_year` | integer | 否 | 财年 | 年份 | `2025` |
| `revenue` | decimal | 否 | 营业收入 | 数字，单位元 | `20000000.00` |
| `net_profit` | decimal | 否 | 净利润 | 数字，单位元 | `2100000.00` |
| `total_assets` | decimal | 否 | 总资产 | 数字，单位元 | `50000000.00` |
| `tax_status` | string | 否 | 纳税状态 | 原文 | `依法纳税` |
| `social_security_status` | string | 否 | 社保状态 | 原文 | `依法缴纳社保` |
| `file_path` | string | 否 | 附件路径 | 审计报告等 | `...` |
| `notes` | text | 否 | 备注 | 投标使用提示 | `适用于近三年财务要求` |

---

## 18. `performance_records` 业绩信息表

### 业务作用

保存公司历史业绩，可用于商务评分、类似项目证明和方案素材引用。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 业绩 ID | 系统生成 | `perf_001` |
| `company_id` | string | 是 | 公司 ID | 关联公司 | `co_001` |
| `project_name` | string | 是 | 业绩项目名称 | 合同或中标通知书名称 | `某平台建设项目` |
| `client_name` | string | 否 | 客户名称 | 合同甲方 | `某某局` |
| `industry_domain` | string | 否 | 行业领域 | 标准化分类 | `信息化` |
| `contract_amount` | decimal | 否 | 合同金额 | 数字，单位元 | `1800000.00` |
| `contract_date` | date | 否 | 合同日期 | 标准日期 | `2024-05-01` |
| `acceptance_date` | date | 否 | 验收日期 | 标准日期 | `2025-01-10` |
| `project_scope` | text | 否 | 项目内容 | 合同范围或实施内容 | `...` |
| `proof_files` | json | 否 | 证明材料 | 合同、中标通知书、验收报告路径 | `["..."]` |
| `reusable_points` | text | 否 | 可复用亮点 | 用于投标方案或业绩描述 | `...` |
| `tags` | json | 否 | 标签 | 行业、技术、客户类型 | `["政府","平台建设"]` |

---

## 19. `historical_cases` 历史案例库表

### 业务作用

保存历史项目复盘、相似案例、得失分经验、风险处理方式。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 案例 ID | 系统生成 | `case_001` |
| `case_title` | string | 是 | 案例标题 | 内部命名 | `某政务项目高分技术方案复盘` |
| `related_project_id` | string | 否 | 关联项目 ID | 可为空 | `prj_old_001` |
| `industry_domain` | string | 否 | 行业领域 | 标准化分类 | `政务信息化` |
| `case_type` | enum | 是 | 案例类型 | 成功案例、失败案例、风险案例、复盘案例 | `成功案例` |
| `summary` | text | 是 | 案例摘要 | 说明背景和结果 | `...` |
| `success_factors` | text | 否 | 成功因素 | 可复用经验 | `...` |
| `failure_reasons` | text | 否 | 失败原因 | 失败案例填写 | `...` |
| `risk_points` | text | 否 | 风险点 | 审查和决策可引用 | `...` |
| `reuse_suggestion` | text | 否 | 复用建议 | 适用场景 | `...` |
| `tags` | json | 否 | 标签 | 检索标签 | `["技术方案","高分"]` |

---

## 20. `historical_bid_files` 历史投标文件表

### 业务作用

保存历史商务标、技术标、响应表、偏离表、终稿文件等索引。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 历史投标文件 ID | 系统生成 | `hbf_001` |
| `related_project_id` | string | 否 | 关联项目 ID | 可为空 | `prj_old_001` |
| `file_type` | enum | 是 | 文件类型 | 商务标、技术标、报价文件、响应表、偏离表、终稿、其他 | `技术标` |
| `file_name` | string | 是 | 文件名 | 原始文件名 | `技术标.docx` |
| `file_path` | string | 否 | 文件路径 | 本地或存储路径 | `...` |
| `version` | string | 否 | 版本 | 初稿、终稿、V1 等 | `终稿` |
| `project_name` | string | 否 | 项目名称 | 方便脱离项目查询 | `...` |
| `bid_result` | enum | 否 | 投标结果 | 中标、未中标、未知 | `中标` |
| `reusable_sections` | text | 否 | 可复用章节 | 例如项目实施方案、售后方案 | `...` |
| `tags` | json | 否 | 标签 | 行业、方案类型 | `["技术标","政务"]` |

---

## 21. `solution_materials` 方案素材库表

### 业务作用

保存可直接用于生成技术标、商务标和响应材料的段落素材。

### 字段设计

| 字段名 | 类型 | 必填 | 含义 | 口径 | 格式 / 示例 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 素材 ID | 系统生成 | `mat_001` |
| `material_type` | enum | 是 | 素材类型 | 技术方案、商务响应、实施计划、售后服务、质量保障、应急预案、培训方案、其他 | `实施计划` |
| `title` | string | 是 | 素材标题 | 内部命名 | `项目进度管理方案` |
| `content` | text | 是 | 素材正文 | 可直接进入生成上下文 | `...` |
| `applicable_domain` | string | 否 | 适用领域 | 信息化、物业、设备等 | `信息化` |
| `applicable_project_type` | string | 否 | 适用项目类型 | 服务、货物、工程 | `服务` |
| `quality_level` | enum | 否 | 素材质量 | 高、中、低、待优化 | `高` |
| `source_case_id` | string | 否 | 来源案例 | 关联 `historical_cases.id` | `case_001` |
| `source_bid_file_id` | string | 否 | 来源投标文件 | 关联历史投标文件 | `hbf_001` |
| `tags` | json | 否 | 标签 | 检索标签 | `["进度","实施"]` |
| `confirmed_status` | enum | 是 | 确认状态 | 未确认、已确认、需复核 | `已确认` |

---

# 五、后续扩展表

## 22. `bid_generation_tasks` 标书生成任务表

### 业务作用

记录每次商务标、技术标、响应表、审查报告生成任务。

### 核心字段

| 字段名 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 生成任务 ID |
| `project_id` | string | 项目 ID |
| `task_type` | enum | 商务标、技术标、响应表、偏离表、审查报告 |
| `input_requirements` | json | 输入的资格、评分、商务、技术要求 ID |
| `retrieved_knowledge_ids` | json | RAG 检索到的知识 ID |
| `output_markdown` | text | 生成结果 Markdown |
| `status` | enum | 生成中、成功、失败、已人工确认 |

---

# 六、推荐落地顺序

## 阶段 1：先做可用数据库

优先落地：

```text
projects
source_documents
document_sections
document_chunks
project_profile
qualification_requirements
rejection_items
business_requirements
technical_requirements
scoring_items
review_findings
solution_materials
```

这一阶段不需要马上做向量库，先保证结构化结果能入库、能查、能改、能追溯。

## 阶段 2：接 RAG

再落地：

```text
chunk_embeddings
performance_records
historical_cases
historical_bid_files
company_qualifications
company_personnel
financial_records
```

开始做关键词检索 + 向量检索混合检索。

## 阶段 3：接生成和决策

最后落地：

```text
bid_generation_tasks
投标决策表
报价策略表
响应偏离表
```

这时可以进入自动生成商务标、技术标、偏离表、审查报告和是否投标建议。

参考资料：

LangChain RAG / retrieval docs: https://python.langchain.com/docs/concepts/rag/
LlamaIndex documents and nodes: https://docs.llamaindex.ai/en/stable/module_guides/loading/documents_and_nodes/
Haystack document store / metadata docs: https://docs.haystack.deepset.ai/docs/document-store
Open Contracting Data Standard: https://standard.open-contracting.org/latest/en/schema/reference/

