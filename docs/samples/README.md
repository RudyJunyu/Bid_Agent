# 解析样例招标文件

本目录存放公开可获取的政府采购招标文件，供后续解析、抽取、评测使用。  
文件均来自政府公开渠道或示范文本发布页，**仅作软件验证与算法评测，不用于投标或商业转售**。

## 文件清单

| 文件 | 类型 | 页数约 | 项目 | 来源 |
|---|---|---|---|---|
| `01-anyang-zhengwu-yunwei.pdf` | 服务／运维 | 94 | 安阳市政务大数据中心第二批市本级政务信息化运维 | [河南省政府采购网公开 PDF](https://zfcg.henan.gov.cn/cmsweb35rc67w/anyang/rootfiles/2026/08/10/eb2d3b5ab3e44c179d2d347cfa8fdfd7.pdf) |
| `02-anhui-shuili-wenxianxitong.pdf` | 货物 | 100 | 安徽水利水电职业技术学院文献管理系统升级和读者服务设备升级 | [示范／公开文本 CDN](https://zhengxin-pub.cdn.bcebos.com/tender/a64b9ebddacff5045b8ede62f8e2d3ba/%E6%8B%9B%E6%A0%87%E6%96%87%E4%BB%B6%E6%AD%A3%E6%96%87.pdf) |
| `03-anhui-shuiwu-duanxin.pdf` | 服务 | 75 | 国家税务总局安徽省税务局短信服务项目 | [安徽税务局公开下载](https://anhui.chinatax.gov.cn/module/download/downfile.jsp?classid=0&filename=239d3f11b89340de936900d0a00e1830.pdf) |
| `04-dongbei-daxue-yunxing-tuoguan.pdf` | 服务 | 较大 | 东北大学浑南校区运行保障与服务托管项目 | [中国政府采购网 OSS](http://download.ccgp.gov.cn/oss/download?uuid=1A7E52A21C3FF680A7D56CBD85D8A6) |
| `05-beijing-zhengwuyun-zuyong.pdf` | 服务／云资源 | 138 | 北京市住建委综合事务中心 2026 年度市级政务云租用 | [北京市公共资源交易中心](https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202609/0215485278eq.pdf) |
| `06-shenzhen-xiaofang-yunwei.pdf` | 服务／运维 | 114 | 深圳市消防救援支队 2024 年度信息化运维服务 | [中国政府采购网 OSS](http://download.ccgp.gov.cn/oss/download?uuid=BF7F16B2D956CCCC77816754C70118) |

覆盖场景：政务信息化运维、货物类设备、短信服务、物业／运行托管、云资源租用。  
便于后续对照 B07 六类要求（概览、资格、废标、商务、技术、评分）做样本标注。

## 使用建议

1. 优先用工作台上传并解析：原生 PDF 文本层样本与扫描件策略均可测。
2. 评测时独立建项目，勿与生产数据混用。
3. 标注证据时记录文件名、章节／页码；本目录文件版权归原发布单位，引用请保留来源链接。
4. 若需补充 DOCX／扫描件样本，另放入本目录并更新本表。

## B10 检索评测样例

见 [retrieval/](retrieval/README.md)：先重建索引，再按 `req:`／`sec:`／`asset:` chunk id 填写 `relevant_ids` 跑 Recall@K。

## B07 黄金标注

| 标注 | 说明 |
|---|---|
| [golden/01-anyang-zhengwu-yunwei.json](golden/01-anyang-zhengwu-yunwei.json) | 安阳样例概览／资格／废标黄金字段 |
| [golden/01-anyang-zhengwu-yunwei.recall.json](golden/01-anyang-zhengwu-yunwei.recall.json) | `b07-rule-v2` 召回快照（概览 9/9） |
| [golden/01-anyang-zhengwu-yunwei.hybrid.recall.json](golden/01-anyang-zhengwu-yunwei.hybrid.recall.json) | `b07-hybrid-v1`（硅基流动）召回快照（概览 9/9） |

```bash
# 规则抽取：
curl -sS -X POST "http://127.0.0.1:8080/api/v1/document-versions/<version_id>/requirements/extract" \
  -H 'Content-Type: application/json' -d '{}'
# LLM 精抽（需 LLM_API_KEY；可能 1–2 分钟）：
curl -sS --max-time 300 -X POST "http://127.0.0.1:8080/api/v1/document-versions/<version_id>/requirements/extract" \
  -H 'Content-Type: application/json' \
  -d '{"use_llm":true,"llm_vendor":"siliconflow","llm_model":"Qwen3-8B (轻量)"}'
python scripts/eval_requirement_recall.py \
  --golden docs/samples/golden/01-anyang-zhengwu-yunwei.json \
  --base-url http://127.0.0.1:8080 \
  --version-id <version_id>
```

下载日期：2026-11-02。
