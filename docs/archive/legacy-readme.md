# 投标工具箱

投标工具箱是一个面向招标文件解析、核对和标书生成的本地桌面工具。项目由 Python FastAPI 后端和 Electron 桌面前端组成，支持解析 PDF、Word、图片、HTML 等招标文件，并调用大模型提取投标人须知、商务内容、技术要求、资格审查和评分要求。

本仓库会持续更新。`.env` 中的 API Key、Token、本地路径等个人配置不公开，请使用 `.env.example` 作为配置模板。

## 下载后快速启动

Windows 用户下载或解压项目后，推荐直接双击项目根目录下的：

```text
run.bat
```

也可以双击：

```text
start.bat
```

启动脚本会自动完成以下事情：

```text
1. 检查项目目录
2. 创建本地 Python 虚拟环境 .venv
3. 根据 requirements.txt 安装后端依赖
4. 根据 electron_client/package.json 安装前端依赖
5. 启动 FastAPI 后端服务
6. 打开 Electron 前端界面
```

首次启动需要联网安装依赖，可能需要几分钟；第二次启动会复用已安装的 `.venv` 和 `node_modules`，速度会快很多。脚本会把启动日志写入 `logs/startup.log`，后端日志写入 `logs/backend.out.log` 和 `logs/backend.err.log`。

如果脚本提示找不到 Python 或 Node.js，请先安装：

- Python 3.10、3.11 或 3.12
- Node.js LTS

不建议使用 Python 3.13 / 3.14。Windows 上很多依赖包（如 numpy、OCR、向量检索相关包）可能没有对应版本的预编译 wheel，会触发本地编译并导致安装失败。启动脚本会优先查找 Python 3.12 / 3.11 / 3.10；如果发现项目 `.venv` 是 Python 3.13 / 3.14，会自动重建虚拟环境。

敏感配置仍然放在 `.env`，不要提交到 GitHub。可以复制 `.env.example` 后填写自己的 API Key、模型地址和 MinerU Token。

## 招投标智能体能力设计

项目整体按六层能力建设，目标是从“文件读懂”逐步扩展到“投标生成、审查和辅助决策”：

```text
1. 文件解析层 `[已完成基础版，持续增强中]`
   ** 核心目标：减少人工判断环节，增强混合文档的自动兜底能力，并提前引入结构化的视角。 ** 
   -> 读懂招标文件、投标文件、合同、附件
   -> 支持 PDF、Word、图片、HTML 等格式
   -> 识别原生文本、扫描件、图文混排、表格、图片和页段结构

   ** 招标文件切片 **
   -> RAG 切片不按整章粗切：小表按表格行切片，大表先生成 table_overview，再按每 3 行打包为 table_row_group；列表项、业务条款、段落块和章节摘要继续切成 document_chunks;每个 chunk 携带 hierarchy_path、item_type、parent_table_header、importance_score、module、vector_filter 等 metadata

2. 结构化抽取层 `[已完成基础版，持续增强中]`
   ** 核心目标：把招标文件抽成可入库、可溯源、可检索、可生成的原子数据。 **
   -> 抽取策略：轻量级两阶段抽取 project_profile 和 section_tree；第一阶段用规则、正则、标题样式、编号模式和前几页表格快速生成候选项目基础信息与章节树，第二阶段仅对缺失或不确定字段调用 LLM 补全，并只传局部上下文
   -> 再按模块抽取投标人须知、商务内容、技术要求、资格审查、废标项、评分要求；默认使用 Markdown 快速抽取，JSON Schema 结构化抽取作为可选增强
   -> 每条原子数据都保留 source_chunk_id、source_text、source_heading、evidence_snippet，方便回查原文和人工复核
   -> 表格清洗为独立业务行：商务条款、技术参数、资格要求、废标情形、评分点分别入库为对应表
   -> 入库时做基础标准化：金额统一为 CNY 数值（如 500万元 -> 5000000，不在数值字段里保留“万元/元”），期限统一为日历天数，日期统一为 ISO 格式，风险等级和状态使用 enum
   -> 通过 source_chunk_id 和关键词相似度建立跨模块引用，例如商务要求关联技术要求、评分项，为后续生成检查清单做准备
   -> 资格审查和废标项先用宽关键词、章节标题和规则重排召回疑似片段，再交给轻量模型复核，最后由大模型精提取，兼顾速度、召回率和完整性
   -> 向量索引使用 sentence-transformers 中的 BAAI/bge-large-zh-v1.5 模型，再用 ChromaDB 持久化索引；chunk_embeddings 记录 SQLite chunk 与 Chroma vector_id 的映射，重排模型选用 BAAI/bge-reranker-v2-m3 模型。

3. 知识沉淀层 `[SQLite 基础版完成，Chroma 向量索引基础版已接入]`
   ** 核心目标：将解析后的结构化信息（如条款、评分点）与原始文档的语义切片（document_chunks）持久化、标准化，并建立起可追溯、可检索、可进化的一套知识基底。
   -> 建立企业内部数据库，包括公司信息、资质管理、人员信息、财务信息、业绩信息、历史投标文件
   -> 建立项目表，沉淀项目名称、编号、预算、招标人、代理机构、时间节点
   -> 建立规则库，沉淀资格规则、评分规则、废标规则、响应规则
   -> 建立案例库，沉淀历史项目、相似项目、投标经验和常见风险
   -> 建立条款库，沉淀合同条款、商务条款、技术条款、审查条款
   -> 建立方案素材库，沉淀商务标、技术标、服务方案、响应材料模板

4. 生成层 `[规划中，已预留标书生成入口]`
   -> 生成招标文件
   -> 生成商务标、技术标、响应表、偏离表
   -> 生成审查报告、风险报告、投标决策建议

5. 审查层 `[部分完成]`wiki
   -> 检查合规性、完整性、一致性
   -> 检查响应偏离、漏项、矛盾项和废标风险
   -> 使用正则、宽关键词回查、原文证据片段和提取结果溯源辅助核验
   -> 可选择支持深度思考的模型追加大模型复核意见

6. 辅助决策层 `[规划中]`
   -> 判断是否投标
   -> 评估风险大小、胜率高低
   -> 辅助制定报价策略、响应策略和投标优先级
```

当前完成度说明：

- `已完成基础版`：已有可用功能链路，后续主要做稳定性、速度和准确率增强。
- `前端基础版完成`：前端已有可用录入、查看、编辑和本地保存能力，后续接后端数据库、附件管理和检索增强。
- `部分完成`：已有入口或核心能力，但还没有覆盖完整业务闭环。
- `规划中`：README 中明确为后续建设方向，当前尚未形成完整功能。

## 当前技术路径

```text
招标文件
  -> Electron 桌面端上传
  -> FastAPI 后端接收
  -> 智能解析两层处理
      -> 第一层：解析层
          -> 判断 PDF 类型：原生文本 PDF / 扫描件 PDF / 图文混排 PDF
          -> 极简纯文本 PDF：pdfplumber 轻量文本抽取
          -> 原生复杂 PDF：统一优先走 MinerU Pipeline / MinerU 并行页段
          -> 扫描件 PDF：OCR / MinerU VLM
          -> 图文混排 PDF：MinerU VLM / MinerU 并行页段
          -> Word：docx2python / python-docx，DOCX 图片提取位置、OCR 和签章/签字线索
      -> 第二层：结构还原层
          -> 尽量保留页码、标题层级、章节、段落、表格、图片说明、页眉页脚线索
          -> 基于 Markdown 标题、font-size/bold 线索、编号模式（一、/ 1. / 1.1）重建标题层级树
  -> 统一中间格式：Markdown 正文 + JSON Schema 结构化元数据
      -> Markdown 正文：保留原文段落、标题、列表、表格和图片占位，方便人工阅读和后续生成引用
      -> 章节 JSON：保留 section_id、title、level、hierarchy_path、page_start、page_end、source_text 等结构信息
      -> 表格 JSON：切片前先处理类合并单元格，再判断大表 / 小表；小表保留逐行语义，大表生成 table_overview 并按每 3 行打包 table_row_group，同时保留 headers、rows、header_paths、cell_header_map、parent_table_header 等表格语义
      -> 图片 JSON：DOCX / PDF 图片元数据挂到相邻章节，保留 image_id、page、nearby_text、OCR/VLM 描述、签章/签字线索、缩略图/压缩 base64 和 has_multimodal_embedding 标志，后续可接 CLIP 等多模态 embedding 做图文统一检索
      -> document_chunks metadata：保留 hierarchy_path、item_type、parent_table_header、importance_score、vector_filter，支撑后续 RAG 过滤和排序
      -> 章节摘要 chunk：作为章节级 / 模块级向量检索入口，metadata 中通过 vector_role=section_summary、summary_of=section_id 与普通 chunk 区分；检索时先用摘要 chunk 路由到相关章节，再优先返回该章节下的子 chunk，避免摘要本身和正文重复抢答案
  -> 模块候选片段召回
      -> 宽关键词召回
      -> 模块语义 query 召回，如商务要求使用“付款方式、合同价款、履约保证金、质保金、发票要求”等查询描述
      -> 标题命中加权
      -> 表格 / 列表 / 数值线索加权
      -> 负向噪声扣分
      -> Top 候选截断
  -> 大模型两阶段分析
      -> 第 0 步：生成 project_profile 和全文 section_tree
      -> 第 1 步：商务内容、技术要求、资格审查、评分要求四路专项并发
      -> 专项 Prompt 携带 project_profile 和 section_tree，并禁止改写项目基本信息
      -> 资格审查专项前，后台自动调用轻量模型逐章预筛“疑似资格审查 / 符合性审查 / 废标或否决投标”段落
      -> 专项模块默认按 Markdown 快速输出并直接展示；需要强结构化入库时，可开启 JSON Schema 输出后再转换为 Markdown 表格展示
      -> 每个原子对象强制携带 source_chunk_id 和 source_text，风险等级、状态、评分类型、废标法律性质等字段使用 enum 归一化
  -> 输出质量后处理
      -> 表格行去重
      -> 句子 / 小点去重
      -> 《材料名称》去重
      -> 金额、时间、日期标准化写入 metadata
      -> 商务要求与技术要求、评分项建立跨模块引用
      -> 原子条目拆分后入库
  -> 正则与关键词辅助校验 / 评分上下文筛选
  -> 内容审查智能体
      -> 正则检查各模块关键字段覆盖率
      -> 区分“原文存在但提取缺失”“提取存在但原文未命中”“原文和提取均命中”
      -> 回查原文证据片段，辅助人工快速定位
      -> 对提取结果做原文溯源评分
      -> 可选大模型深度审查，输出高风险问题和人工核对建议
  -> Electron 前端模块化展示
```

## 功能概览

- **文件解析**：支持 PDF、Word、图片、HTML；自动判断原生文本、扫描件、图文混排和表格/图片内容，按文件特征选择 pdfplumber、MinerU、OCR、docx2python 等解析方式。
- **结构化抽取**：先生成项目画像和章节树，再抽取投标人须知、商务内容、技术要求、资格审查、废标项和评分要求；默认走 Markdown 快速抽取，抽取为空时会回退到本地候选片段展示，JSON Schema 可按需开启。
- **前端展示与编辑**：按五大模块展示解析结果，支持 Markdown 表格渲染、图片卡片展示、字段编辑和重新分析；投标人须知包含各种时间安排、暗标、代理商投标、联合体投标等按钮字段。
- **项目库与知识库**：解析结果写入 SQLite，可查看项目、章节、切片、条款、评分点和审查发现；知识库支持公司信息、资质、人员、财务、业绩、历史案例、历史投标文件和方案素材管理。
- **RAG 检索**：document_chunks 按小表表格行、大表 table_overview / table_row_group、列表项、业务条款、段落块、图片证据和章节摘要切片；关键词召回使用 SQLite FTS5 + BM25，未命中时回退到轻量关键词计分；语义召回使用 `BAAI/bge-large-zh-v1.5` 生成 Chroma 向量索引，并用 `BAAI/bge-reranker-v2-m3` 重排；项目库内置智能检索入口，可按当前项目召回原文证据、章节路径、chunk_id 和 metadata。
- **标书生成辅助**：项目库内置“标书目录生成”浮层，可根据招标文件编制要求、资格条件、商务要求、技术要求、评分项和废标风险自动生成 Markdown 目录建议。
- **生成主流程**：招标解析核对完成后直接进入“标书生成工作台”，第一步生成并编辑标书目录，第二步按目录章节逐节生成正文草稿，第三步汇总已生成章节并导出 Markdown 初稿。
- **审查与运维**：支持手动执行内容审查，回查原文证据并识别缺失、矛盾和废标风险；Electron 可自动启动 FastAPI 后端，并通过 `/health` 做端口和连通性检查。

### 关于chunk的补充
- 章节摘要： 按标题层级（如 ## 第三章）合并下属所有块，调用一次 LLM 生成该章节的摘要，存入一个独立的摘要 Chunk，用于高层级的聚合语义匹配，并记录元数据信息（切片类型、章节id等）
- 表格切片： 先处理类合并单元格，生成header_path以及cell_header_map，然后对小表逐行切，每一行生成一个 chunk，metadata会带如下例信息：
{
  "cells": ["项目实施方案", "方案完整性", "10分"],
  "header_paths": ["评分项", "评分标准", "分值"],
  "cell_header_map": {
    "评分项": "项目实施方案",
    "评分标准": "方案完整性",
    "分值": "10分"
  }
}
-- 大表格处理方式：overview + 每3行一组，首先生成一个表格说明chunk，chunk_type = 表格说明，item_type = table_overview，table_size = large，类似：
表格说明：评分办法 > 综合评分表
字段：评分项 > 评分标准 > 分值
行数：80
用途：该 chunk 用于说明大表结构，具体数据位于 table_row_group chunk。
每 3 行打包成一个 chunk
  {
    "parent_table_overview_id": "table_001_overview",
    "row_start": 1,
    "row_end": 3,
    "rows": [
      {
        "row_index": 1,
        "cells": [...],
        "cell_header_map": {...}
      }
    ]
  }

- 列表项 / 业务条款切片： 处理标题、编号、小点、列表。这些会被拆成独立条目，每个条目一个 chunk。metadata 会记录：
  {
    "source_format": "markdown_list",
    "item_type": "列表项",
    "section": "项目实施要求",
    "item_name": "项目实施要求",
    "sequence": "1"
  }
- 段落块切片：段落不是每一行都切，而是会先做短段合并：
- 图片证据 chunk，OCR + AI 描述写成图片证据 chunk
- 之后每一个chunk会统一补metadata：
  {
    "hierarchy_path": "章节路径",
    "item_type": "切片类型",
    "parent_table_header": "表格上下文",
    "importance_score": 1.0,
    "module": "所属模块",
    "section_id": "来源章节",
    "vector_filter": {
      "module": "...",
      "item_type": "...",
      "hierarchy_path": "..."
    }
  }

## Chroma 向量索引

项目解析并结构化入库后，后端会自动尝试把 `document_chunks` 写入本地 Chroma。SQLite 仍是主数据库，Chroma 负责语义检索；`chunk_embeddings` 表会记录 SQLite `chunk_id` 与 Chroma `vector_id` 的映射。

启用条件：

```env
BID_VECTOR_STORE_ENABLED=true
HF_ENDPOINT=https://hf-mirror.com
CHROMA_PERSIST_DIR=.chroma
CHROMA_COLLECTION=bid_document_chunks
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_ID=BAAI/bge-large-zh-v1.5
RERANKER_ENABLED=true
RERANKER_MODEL_ID=BAAI/bge-reranker-v2-m3
RERANKER_TOP_K_MULTIPLIER=4
```

默认使用 `sentence-transformers` 本地加载 `BAAI/bge-large-zh-v1.5` 生成 chunk 向量，并用 `BAAI/bge-reranker-v2-m3` 对 Chroma 初召回结果重排。后端默认优先使用 `HF_ENDPOINT=https://hf-mirror.com` 下载 HuggingFace 模型；如需使用官方源，可在 `.env` 中覆盖该变量。若要改用 OpenAI-compatible embedding，可设置 `EMBEDDING_PROVIDER=openai`，并配置 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL` 和远程 embedding 模型名。

前端项目库已接入该接口：选择项目后，在“智能检索”里输入问题，默认只检索当前项目，可按模块过滤并展示命中的原文片段、章节路径、页码、chunk_id 和 `metadata_json`。

向量查询接口：

```text
POST http://127.0.0.1:8000/vector/search
```

请求示例：

```json
{
  "project_id": "prj_xxx",
  "query": "付款方式、履约保证金、发票要求",
  "module": "商务内容",
  "item_type": "表格行",
  "top_k": 8
}
```

可过滤字段来自 `document_chunks` 基础列和 `metadata_json`，包括 `project_id`、`module`、`item_type`、`hierarchy_path`、`parent_table_header` 等。删除项目时，后端会同步尝试删除该项目在 Chroma 中的向量。

## 项目结构

```text
.
├── bid_parser_api.py          # FastAPI 后端接口，包括上传、解析、分析和流式接口
├── bid_analysis_service.py    # 招标文件分析服务，负责解析后并发调用大模型
├── bid_analysis_prompts.py    # 大模型分析 Prompt
├── bid_structured_extraction.py # JSON Schema 结构化抽取、enum 约束和溯源字段转换
├── bid_document_parser.py     # 招标文件解析入口和章节拆分
├── bid_parse_strategy.py      # 解析方式推荐和解析质量报告
├── bid_section_retriever.py   # 模块候选片段混合召回，减少大模型全文重复读取
├── bid_vector_store.py        # Chroma 向量索引、embedding 和语义检索接口
├── bid_qualification_prefilter.py # 资格审查/废标项轻量模型逐章预筛
├── bid_image_analysis.py      # 文档图片分析和 OCR 辅助能力
├── bid_database.py            # SQLite 数据库初始化、知识库 CRUD 和结构化入库
├── MinerU_pdf_parse_tool.py   # MinerU API 文档解析工具
├── llm_client.py              # OpenAI-compatible 大模型客户端，支持同步、异步、流式
├── llm_model_config.py        # 前端模型名称与真实模型 ID 映射
├── SerpApi_search_tool.py     # SerpApi 搜索工具
├── plan_and_solve_agent.py    # Plan-and-Solve Agent 逻辑
├── run_plan_and_solve.py      # 命令行入口
├── requirements.txt           # Python 依赖
├── DATABASE_SCHEMA_DESIGN.md  # 招投标智能体数据库表设计
├── docs/
│   └── 招投标智能体数据库表结构.xlsx  # 当前 SQLite 表结构 Excel
├── scripts/
│   └── export_db_schema_excel.py      # 表结构 Excel 导出脚本
└── electron_client/           # Electron 桌面客户端
    ├── main.js
    ├── preload.js
    ├── renderer.html
    ├── renderer.js
    ├── styles.css
    ├── package.json
    └── package-lock.json
```

## 环境要求

- Python 3.10 或更高版本
- Node.js 18 或更高版本
- npm
- 可用的大模型 API Key
- 如使用 MinerU API，需要 MinerU API Token
- 如使用 Tesseract OCR，需要本机安装 Tesseract

## 安装 Python 依赖

建议使用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Python 依赖包括：

- `fastapi`、`uvicorn`：后端 API 服务
- `openai`：OpenAI-compatible 大模型调用
- `python-dotenv`：读取本地环境变量
- `pymupdf`、`pymupdf4llm`：原生 PDF 快速抽取和 Markdown 转换
- `docling`：复杂原生 PDF 的结构化解析、阅读顺序和表格结构还原
- `pdfplumber`：PDF 预检、fallback 文本解析和简单表格抽取
- `pypdf`：PDF 按页段拆分，用于 MinerU 并行页段解析
- `docx2python`、`python-docx`：Word 文档解析
- `pillow`、`opencv-python`、`rapidocr-onnxruntime`、`pytesseract`：图片和 OCR 辅助解析
- `chromadb`：本地向量库，用于对 `document_chunks` 建立 Chroma 语义索引
- `sentence-transformers`：本地加载 `BAAI/bge-large-zh-v1.5` 和 `BAAI/bge-reranker-v2-m3`，用于 chunk embedding 和 rerank
- `requests`、`pydantic`、`python-multipart`：接口、校验和上传支持

## 安装 Electron 客户端依赖

```powershell
cd electron_client
npm install
```

Electron 客户端主要依赖：

- `electron`
- `electron-builder`

## 配置环境变量

复制模板：

```powershell
copy .env.example .env
```

编辑 `.env`，填入自己的密钥和模型信息：

```env
LLM_MODEL_DISPLAY_NAME=
LLM_MODEL_ID=your-model-id
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_TIMEOUT=120
LLM_MAX_CONCURRENCY=5
LLM_STREAM_MAX_CONCURRENCY=4
BID_FAST_MARKDOWN_EXTRACTION=true
BID_STRUCTURED_OUTPUT_ENABLED=false
BID_VECTOR_STORE_ENABLED=true
CHROMA_PERSIST_DIR=.chroma
CHROMA_COLLECTION=bid_document_chunks
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_ID=BAAI/bge-large-zh-v1.5
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=
EMBEDDING_BATCH_SIZE=32
RERANKER_ENABLED=true
RERANKER_MODEL_ID=BAAI/bge-reranker-v2-m3
RERANKER_TOP_K_MULTIPLIER=4
BID_RETRIEVAL_CONTEXT_CHARS=4500
BID_RETRIEVAL_MAX_CHARS=52000

BID_QUAL_PREFILTER_ENABLED=true
BID_QUAL_PREFILTER_MODEL_ID=Qwen/Qwen3-8B
BID_QUAL_PREFILTER_RULE_RECALL_ENABLED=true
BID_QUAL_PREFILTER_RULE_MAX_CHARS=30000
BID_QUAL_PREFILTER_RULE_CONTEXT_CHARS=3600
BID_QUAL_PREFILTER_MAX_CHUNKS=24
BID_QUAL_PREFILTER_CHUNK_CHARS=3600
BID_QUAL_PREFILTER_BATCH_SIZE=6
BID_QUAL_PREFILTER_CONCURRENCY=2
BID_QUAL_PREFILTER_CONFIDENCE=0.45

MINERU_API_TOKEN=your-mineru-token
MINERU_REQUEST_TIMEOUT=60
MINERU_PARALLEL_PAGE_CHUNK_SIZE=30
MINERU_PARALLEL_MAX_WORKERS=3

SERPAPI_API_KEY=your-serpapi-key
```

注意：`.env` 已加入 `.gitignore`，不要提交真实密钥。

## 一键启动

推荐双击项目根目录下的：

```text
start.bat
```

一键启动会自动完成：

- 检查项目目录
- 检查 8000 端口
- 如果检测到旧的本项目后端，会自动停止旧进程
- 启动 FastAPI 后端
- 等待 `/health` 通过
- 启动 Electron 前端

启动后可打开健康检查确认：

```text
http://127.0.0.1:8000/health
```

如果看到 `status: ok` 和 `build` 字段，说明后端是新版。

## 手动启动后端

在项目根目录启动 FastAPI：

```powershell
python -m uvicorn bid_parser_api:app --host 127.0.0.1 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 手动启动前端

```powershell
cd electron_client
npm.cmd start
```

前端默认连接：

```text
http://127.0.0.1:8000
```

Electron 开发模式会尝试自动启动 FastAPI 后端，并检查：

```text
http://127.0.0.1:8000/health
```

如果后端端口发生变化，请在前端“后端地址”中同步修改。Electron 会按填写的端口重新检查连接。

## 自动检查与端口诊断

前端在上传解析或重新分析前，会先执行后端自动检查：

```text
Electron 主进程
  -> 检查 127.0.0.1:端口 /health
  -> 如果未连接，自动执行 python -m uvicorn bid_parser_api:app --host 127.0.0.1 --port 端口
  -> 最多等待 30 秒
  -> 捕获 uvicorn stdout / stderr 日志
  -> 前端再次请求 /health
```

如果仍然失败，前端结果区会显示：

- 错误类型和错误信息
- 当前端口
- `/health` 健康检查是否通过
- Electron 是否托管了后端进程
- 后端目录
- 最近后端启动日志

常见原因：

- Python 没有加入系统 PATH，导致 Electron 无法执行 `python`
- 端口 `8000` 被其他程序占用
- 依赖没有安装完整，例如缺少 `fastapi`、`uvicorn`、`python-multipart`
- 当前运行的是旧的打包 exe，未包含最新源码改动
- 后端启动目录不对，找不到 `bid_parser_api.py`

如果自动启动失败，可以手动启动后端验证：

```powershell
python -m uvicorn bid_parser_api:app --host 127.0.0.1 --port 8000
```

看到 `/health` 返回 `{"status":"ok"}` 后，再启动 Electron 前端。

注意：如果双击的是已经打包的旧 exe，它内部使用的是打包时的 `app.asar`，不会自动读取源码里的最新 `main.js`、`preload.js`、`renderer.js`。测试最新改动请使用：

```powershell
cd electron_client
npm start
```

确认无误后再重新打包：

```powershell
cd electron_client
npm run dist
```

## 常用接口

- `GET /health`
  后端健康检查。

- `POST /bid-documents/parse`
  根据本地路径或远程 URL 解析招标文件。

- `POST /bid-documents/upload`
  上传文件并解析，返回章节和解析质量信息。

- `POST /bid-documents/analyze`
  根据本地路径或远程 URL 解析并调用大模型分析。

- `POST /bid-documents/upload-analyze`
  上传文件，解析后调用大模型分析，返回完整 JSON。

- `POST /bid-documents/upload-analyze-stream`
  上传文件，解析后以 Server-Sent Events 流式返回分析过程和结果。

- `POST /bid-documents/analyze-content`
  使用人工修改后的解析内容重新分析。

- `POST /bid-documents/analyze-content-stream`
  使用人工修改后的解析内容流式重新分析。

## 解析方式

当前支持的解析方式包括：

```text
auto                  自动推荐解析方式
mineru_vlm            MinerU VLM
mineru_pipeline       MinerU Pipeline
mineru_html           MinerU-HTML
mineru_parallel_pages MinerU 并行页段解析
pymupdf4llm           PyMuPDF4LLM 快速 PDF 解析
docling               Docling 结构化 PDF 解析
pdfplumber            本地 PDF fallback 文本解析
docx2python           本地 Word 文本解析
docx2python_image_ocr Word 文本解析 + 图片 OCR
```

`auto` 会根据文件类型、文本量、PDF 图片数量、PDF 表格信号、PDF 页数、DOCX 图片数量等因素推荐解析方式。PDF 会先进入两层智能解析流程：

1. 解析层：判断 PDF 是原生文本 PDF、扫描件 PDF 还是图文混排 PDF。为保证稳定性，原生文本 PDF 的 `auto` 默认使用 `pdfplumber`；`pymupdf4llm` 和 `docling` 保留为手动增强选项；扫描件 PDF 优先使用 OCR / MinerU VLM，图文混排 PDF 优先使用 MinerU 多模态能力。
2. 结构还原层：尽量保留页码、标题层级、章节、段落、表格、图片说明、页眉页脚等结构线索，统一组织为 Markdown。

扫描件 PDF 或含正文图片的图文混排 PDF 会优先推荐 `mineru_vlm` 或 `mineru_parallel_pages`，避免仅依赖本地文本层。`pymupdf4llm` / `docling` 在部分 Windows 环境可能受到 ONNXRuntime、torch 或模型依赖影响，因此不作为默认自动路线。

推荐路由：

```text
原生文本 PDF              -> pdfplumber
需要快速试验原生 PDF       -> 手动选择 pymupdf4llm
需要结构化试验复杂 PDF     -> 手动选择 docling
扫描件 PDF                -> mineru_vlm / mineru_parallel_pages
图文混排 PDF              -> mineru_parallel_pages
手动兜底/排障             -> pdfplumber
```

`mineru_parallel_pages` 主要用于较大的 PDF 招标文件。后端会按页段拆分 PDF，并发调用 MinerU，再按页码顺序合并 Markdown。可通过 `.env` 调整：

```env
MINERU_PARALLEL_PAGE_CHUNK_SIZE=30
MINERU_PARALLEL_MAX_WORKERS=3
```

并发数不要一次调得过高，避免触发 MinerU 接口限流或本地资源占满。

## 大模型分析策略

前端默认模型为 `Qwen3-8B (轻量)`，优先保证可访问性和响应速度。`DeepSeek-V4-Pro`、`Kimi-K2.6 (Pro)` 等 Pro 模型仍保留在模型列表中，适合需要更高质量复核时手动选择；如果服务商返回 `Model is private`，说明当前账号无权调用该模型，需要换用可访问模型或在服务商后台开通权限。

后端会将解析后的文档内容组装为 Markdown + 结构化元数据，然后按两阶段调用大模型：

1. 第 0 步先生成全局 `project_profile` 和全文 `section_tree`，统一项目名称、编号、预算、招标人、代理机构、采购方式、分包等基础信息，并还原章节标题、层级和起始位置。
2. 第 1 步并发执行四个专项抽取任务：商务内容、技术要求、资格审查、评分要求。每个专项任务都会携带全局 `project_profile` 和 `section_tree`，并要求模型不得修改项目基本信息，只能从指定候选章节范围内提取。
3. 资格审查专项会额外走一轮轻量模型预筛：逐章分段标出疑似资格审查、符合性审查、废标/否决投标段落，再把命中片段并入精提取上下文。预筛失败不会中断主流程，会自动回退到规则召回。
4. 专项抽取默认使用 Markdown 快速输出，减少模型兼容性问题；如果开启 `BID_STRUCTURED_OUTPUT_ENABLED=true`，则使用 JSON Schema 结构化输出，并要求每个原子条目带 `source_chunk_id`、`source_text`、`source_heading` 和 `evidence_snippet`。
5. Schema 中对关键枚举值做归一化：风险等级为 `高/中/低/未明确`，废标法律性质为 `资格性/符合性/响应性/其他`，审查状态为 `open/resolved/ignored`，评分类型为 `商务评分/技术评分/价格评分/其他`。

每个模块都会先召回相关章节和命中点前后上下文，再交给大模型提取，避免多个模块反复读取整份长文档。召回策略采用“SQLite FTS5 + BM25 关键词召回、章节标题加权、模块语义 query、Chroma 向量召回、reranker 重排”的混合检索；未启用 FTS5 或无命中时，会回退到轻量关键词计分，宁可多召回一些，也尽量避免漏掉不同招标文件里的同义标题。

默认上下文参数：

```env
BID_FAST_MARKDOWN_EXTRACTION=true
BID_STRUCTURED_OUTPUT_ENABLED=false
BID_RETRIEVAL_CONTEXT_CHARS=4500
BID_RETRIEVAL_MAX_CHARS=52000
```

其中 `BID_FAST_MARKDOWN_EXTRACTION=true` 表示优先使用 Markdown 快速抽取，避免 JSON Schema / Function Calling 兼容性导致四大模块空白。若后续模型稳定且希望强结构化输出，可设置 `BID_FAST_MARKDOWN_EXTRACTION=false` 并开启 `BID_STRUCTURED_OUTPUT_ENABLED=true`。`BID_RETRIEVAL_CONTEXT_CHARS` 控制每个命中点前后的窗口大小，`BID_RETRIEVAL_MAX_CHARS` 控制每个模块最多交给大模型的候选文本长度。

前端可以选择：

- 流式输出
- 非流式输出

流式接口会边分析边返回事件；非流式接口会等待全部分析完成后一次性返回结果。

流式大模型调用默认使用 `LLM_STREAM_MAX_CONCURRENCY=4`，四个专项模块可以并发流式提取。部分 OpenAI-compatible 服务商对多路并发流式请求支持不稳定，若触发连接中断或 `[Errno 22] Invalid argument`，可临时降到 `2` 或 `1`。

## 前端展示与审查

解析结果在 Electron 前端按模块展示：

- 投标人须知：字段化表单展示，支持复制和展开。
- 商务内容：Markdown 展示区，商务条款表格直接渲染为表格。
- 技术要求：Markdown 展示区，技术参数、服务要求和表格内容直接渲染。
- 资格审查：按资格性审查、符合性审查、废标项切换，表格化展示。
- 评分要求：按商务评分、技术评分切换，表格化展示。
- 图片解析：以图片卡片展示，保留图片预览、OCR 文本和 AI 备注。
- 内容审查：Markdown 展示区，正则审查和大模型深度复核结果直接渲染为表格和分节报告。
- 编辑能力：投标人须知可在字段中直接修改；商务、技术、资格、评分、内容审查可通过“编辑”按钮修改原始 Markdown，保存后自动刷新页面展示。

各模块的“展开”按钮使用富文本预览：

- Markdown 表格在展开窗口中仍显示为表格。
- 图片解析在展开窗口中仍显示图片卡片。
- 复制和导出仍使用原始 Markdown / 文本内容，便于留档和二次编辑。

## 知识库

知识库当前已完成 SQLite 后端存储 Demo：前端知识库表单会优先通过 FastAPI 写入本地 SQLite 数据库；如果后端不可用，则自动退回前端 `localStorage` 兜底。

SQLite 数据库默认位置：

```text
data/bid_agent.db
```

该文件属于本地业务数据，已加入 `.gitignore`，不要上传到 GitHub。

当前支持八类知识资产：

- 公司信息：公司简介、联系方式、经营范围、服务能力、服务承诺。
- 资质管理：营业执照、资质证书、体系认证、授权文件和有效期。
- 人员信息：项目经理、技术负责人、团队成员、证书、履历和项目经验。
- 财务信息：审计报告、财务指标、纳税社保、银行资信和财务承诺。
- 业绩信息：历史项目业绩、合同金额、客户类型、验收情况和证明材料。
- 历史案例库：相似项目案例、投标复盘、得失分经验和风险处理记录。
- 历史投标文件：历史商务标、技术标、响应表、偏离表和终稿文件索引。
- 方案素材库：服务方案、技术方案、实施计划、售后运维、质量保障等可复用素材。

当前支持的操作：

- 按知识类型切换
- 新建、编辑、删除知识条目
- 按标题、标签、备注和正文搜索
- 本地自动保存
- JSON 导入和导出

当前后端 Demo 接口：

```text
GET    /knowledge/types
GET    /knowledge/entries
POST   /knowledge/entries
DELETE /knowledge/entries/{entry_id}
GET    /knowledge/export
POST   /knowledge/import
```

## 结构化抽取与入库

解析文件并完成五大模块结构化抽取后，后端会尝试把结果写入 SQLite：

```text
五大模块结果
  -> 项目概览清洗
  -> Markdown 表格解析
  -> 章节与切片入库
  -> 写入 projects / source_documents / document_sections / document_chunks
  -> 写入 project_profile
  -> 写入 business_requirements
  -> 写入 technical_requirements
  -> 写入 qualification_requirements
  -> 写入 rejection_items
  -> 写入 scoring_items
  -> 写入 review_findings
  -> 记录 extraction_runs
```

当前结构化抽取和入库的表职责如下：

| 表名 | 当前写入内容 | 用途 |
| --- | --- | --- |
| `projects` | 项目名称、编号、类别、招标人、代理机构、预算、状态 | 项目主索引 |
| `source_documents` | 文件名称、类型、扩展名、解析方式、解析状态 | 原始文件索引 |
| `document_sections` | 章节标题、顺序、Markdown、纯文本、章节类型 | 保留解析后的章节结构 |
| `document_chunks` | 表格行、列表小点、业务条款、段落块、模块标签、标题路径、元数据 | 后续 RAG 检索和引用 |
| `project_profile` | 投标人须知 / 项目概览字段 | 项目基础事实表 |
| `business_requirements` | 商务条款、所属标题、序号、金额、比例、期限、强制性、元数据 | 商务响应和合同条款复用 |
| `technical_requirements` | 技术小点、所属标题、父级事项、序号、验收标准、重要程度、元数据 | 技术标响应和方案生成 |
| `qualification_requirements` | 资格性审查、符合性审查、需提供资料 | 资格材料核对 |
| `rejection_items` | 废标项、具体表现、风险等级 | 废标风险检查 |
| `scoring_items` | 商务评分、技术评分、评分标准、分值 | 标书生成时对齐评分点 |
| `review_findings` | 内容审查发现、风险等级、建议、状态 | 人工复核和风险闭环 |
| `extraction_runs` | 抽取任务、状态、输入切片、开始结束时间 | 追踪每次解析和抽取过程 |

当前是基础版清洗：已经能把解析结果按表落库并跑通主链路；商务内容和技术要求会按 Markdown 标题、编号和列表小点拆成多条记录，资格审查、废标项、评分项也会保留所属标题、序号和元数据。入库前会对重复句、重复表格行和重复《材料名称》做规范化去重，减少大模型复读造成的冗余记录。`document_chunks` 会优先按表格行、列表小点和段落块生成最小语义单元，并保留 `title_path`、`chunk_type`、`content_markdown`、`page_start`、`page_end`、`metadata_json` 等字段。复杂页码溯源、精细金额/日期标准化、表格跨页合并、向量索引写入后续继续增强。

向量检索的规划是：SQLite 继续保存结构化事实和业务状态，向量数据库保存可语义检索的长文本、条款、评分点、历史案例和方案素材。`chunk_embeddings` 用于记录 SQLite 记录和外部向量库之间的映射关系。

可以通过以下接口查看 SQLite 中所有表和数据量：

```text
GET /database/tables
```

项目库查询与删除接口：

```text
GET  /projects
GET  /projects/{project_id}
DELETE /projects/{project_id}
DELETE /projects/records/{table_name}/{record_id}
```

## 解析质量增强策略

当前默认模型可以使用 `Qwen3-8B (轻量)`，但小模型对长文档、噪声片段和重复材料清单比较敏感。项目已加入一层轻量质量增强链路：

```text
原始章节
  -> 宽关键词召回
  -> 规则重排
      -> 标题命中加权
      -> 表格 / 列表 / 数值线索加权
      -> 模块负向关键词扣分
      -> 候选片段去重
      -> Top 候选截断
  -> 原子粒度 Prompt 抽取
  -> 输出后处理
      -> Markdown 表格行去重
      -> 句子 / 小点去重
      -> 《材料名称》去重
  -> 结构化入库
```

这套策略的目标是：在不新增外部依赖的情况下，减少给大模型的无关上下文，降低重复输出、材料清单复读、评分和资格混淆等问题。

当前已实现：

- `bid_section_retriever.py`：从宽召回升级为“宽召回 + 规则重排 + Top 候选截断”。
- `bid_analysis_prompts.py`：补充原子粒度输出要求，要求一个要求、材料或评分点尽量单独一行。
- `extraction_cleaner.py`：对大模型输出做表格行、句子、小点和《材料名称》去重。
- `bid_database.py`：入库前再次清洗，并在业务表和 `document_chunks` 层做规范化去重。
- `bid_vector_store.py`：使用 `BAAI/bge-large-zh-v1.5` 生成 Chroma 向量索引，并使用 `BAAI/bge-reranker-v2-m3` 对召回结果重排。

后续可继续增强：

- 对历史项目做“旧项目重建切片”和“旧项目重新抽取”，把旧数据升级到新粒度。
- 将 Chroma 向量召回进一步接入专项抽取前的候选片段召回，实现“规则召回 + 向量召回 + reranker”的正式双路召回。

## 性能说明

智能解析为了提高准确率，会同时做 PDF 类型判断、结构还原、图片提取/OCR、五个模块的大模型分析以及评分上下文筛选，因此复杂文件会比单纯文本抽取更慢。PDF 解析已经改为“快解析 + 结构化 + 多模态”的分流策略。常见耗时来源包括：

- `pdfplumber` 只用于确认无版式风险的极简纯文本 PDF，以及 PDF 预检、fallback 和排障。
- `pymupdf4llm` 适合原生文本 PDF 快速试验，但在部分 Windows/ONNXRuntime 环境可能不稳定。
- `docling` 适合原生 PDF 中的表格、章节层级和复杂阅读顺序，但依赖较重，建议手动选择后小范围测试。
- 非极简纯文本的原生 PDF、扫描件 PDF 或图文混排 PDF 会优先调用 MinerU / OCR / VLM。
- `mineru_parallel_pages` 会按页段拆分 PDF，并发提交 MinerU，速度受网络、接口排队和并发数影响。
- PDF / DOCX 图片解析会额外执行图片提取、OCR 和 AI 备注。
- 五个模块的大模型分析会先检索候选片段、规则重排并截断 Top 片段，再并发执行，速度主要受候选片段长度、模型速度、服务商并发限制影响。

## 大模型并发策略

五个模块理论上可以并发调用大模型，但 OpenAI-compatible 服务商经常会对以下场景限制较严：

- 同一 API Key 同时发起多个长上下文请求。
- 多路流式输出同时保持连接。
- Pro / 私有模型有并发、速率或权限限制。
- 单次请求上下文过长，多个请求同时触发超时或连接重置。
- 本机代理、网络波动或服务商排队导致某一路失败，进而触发降级重试。

因此项目默认采用更稳的并发配置：

```env
LLM_TIMEOUT=180
LLM_MAX_CONCURRENCY=2
LLM_STREAM_MAX_CONCURRENCY=4
```

含义：

- `LLM_MAX_CONCURRENCY=2`：非流式批量提取最多同时跑 2 个模块。
- `LLM_STREAM_MAX_CONCURRENCY=4`：四个专项模块默认并发流式输出。
- 如果服务商流式并发不稳定，可以把 `LLM_STREAM_MAX_CONCURRENCY` 临时降到 2 或 1；如果额度充足，再结合 `LLM_MAX_CONCURRENCY` 调整非流式并发。
- 如果仍然失败，优先关闭流式输出，使用非流式稳定提取。

建议使用方式：

- 极简纯文本 PDF 可以使用 `auto`，系统会走 `pdfplumber` 轻量路线。
- 非极简原生 PDF、扫描件、图文混排、图片较多的文件，使用 `auto` 或 `mineru_parallel_pages`，系统会优先走 MinerU。
- 需要本地试验更快或更强结构化效果时，可以手动试 `pymupdf4llm` 或 `docling`。
- 大文件可以先填写页码范围做小范围测试，再解析整份文件。
- 如果 MinerU 限流或速度较慢，可以适当降低 `MINERU_PARALLEL_MAX_WORKERS`。

## 打包桌面端

项目稳定后可以打包 Windows 便携版：

```powershell
cd electron_client
npm run dist
```

打包产物输出到：

```text
electron_client/dist/
```

`electron_client/dist/` 已加入 `.gitignore`，不要提交打包产物。

打包后的 exe 会包含当时的 Electron 前端文件和后端 Python 文件。如果修改了 `electron_client/main.js`、`preload.js`、`renderer.js`、`styles.css` 或后端 `.py` 文件，需要重新执行 `npm run dist` 生成新版 exe。

## 后续计划

- 完善标书生成模块
- 增加 Word / PDF 导出能力
- 增加模板套版能力
- 增加废标项检查和响应完整性检查
- 增加自动化测试和发布流程
