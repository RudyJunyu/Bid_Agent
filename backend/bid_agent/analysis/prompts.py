# -*- coding: utf-8 -*-
"""Prompt builders for bid document analysis."""

import json
import re
from typing import Any, Dict, Iterable, List


DEDUPLICATION_OUTPUT_RULES = """

通用输出约束：
- 相同或高度相似的条款、材料、表单、证明文件只输出一次，不要在同一模块中重复列出。
- 如果原文同一材料在多个位置重复出现，请合并为一条，并在内容中保留关键限制条件。
- 不要把大量材料名称堆在一个长句里；应按表格行或条目拆分。
- 不要连续复读“投标人需提供……”类句式；相同材料名称出现一次即可。
- 尽量采用“一个要求/一个材料/一个评分点一行”的原子粒度，不要把多个互不相同的事项合并在同一行。
- 每条内容尽量保留能回查原文的关键词、数值、期限、分值或证明材料，不要只写概括性短语。
"""


def _with_common_rules(system_prompt: str) -> str:
    return f"{system_prompt.rstrip()}{DEDUPLICATION_OUTPUT_RULES}"


PROJECT_OVERVIEW_SYSTEM_PROMPT = """你是专业的招标文件分析师。请从用户提供的招标文件内容中提取“投标人须知/项目概览”信息。

请严格按下面 16 个字段输出，每个字段单独一行，格式为“字段名：内容”。除按钮字段外，尽量保留招标文件原文表达；没有明确提及则写“未提及”。

1. 项目名称
2. 项目编号
3. 项目类别（服务类，货物类，工程类）和服务年限
4. 包号
5. 项目规模和预算
6. 招标人
7. 招标代理机构
8. 项目所属领域
9. 各种时间安排：重点提取招标文件中提到的全部时间节点，包括但不限于网上报名时间、获取招标文件时间、澄清/答疑时间、投标保证金缴纳时间、投标文件提交截止时间、开标时间、评审时间、项目实施/交付/服务安排时间等
10. 项目要实施的具体内容
11. 主要技术特点
12. 其他关键要求
13. 是否专门面向中小微企业采购：只输出“是”或“否”；原文未提及或无法判断一律输出“否”
14. 是否为暗标：只输出“是”或“否”；原文未提及或无法判断一律输出“否”
15. 是否允许代理商投标：只输出“是”或“否”；原文未提及或无法判断一律输出“否”
16. 是否允许联合体投标：只输出“是”或“否”；原文未提及或无法判断一律输出“否”

要求：
- 只提取与项目概览和投标人须知相关的内容。
- 不要编造招标文件没有说明的信息。
- 不要输出解释、分析过程、寒暄或额外标题。"""


PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE = """请分析以下招标文件内容，提取投标人须知/项目概览信息：

{file_content}"""


TECHNICAL_SCORING_SYSTEM_PROMPT = """你是专业的招标文件技术要求分析师。请从招标文件中提取“技术要求”内容，而不是评分表。

重点关注：
- 服务/货物/工程的技术标准、技术参数、功能要求、性能指标
- 实施范围、交付内容、服务要求、运维要求、验收要求
- 对技术方案、人员、设备、工期、质量、安全、保密等方面的要求
- 主要技术特点和必须响应的技术条款

输出要求：
- 使用清晰的小标题和条目整理。
- 每一个技术要求、交付要求、验收要求、服务要求尽量单独成条，不要把多项要求合并成一个长段落。
- 尽量保留原文表达，尤其是硬性要求、参数、数值、期限和验收标准。
- 未发现技术要求时写“未提及”。
- 不要输出商务评分、技术评分、价格评分或资格审查内容。"""


TECHNICAL_SCORING_USER_PROMPT_TEMPLATE = """请分析以下招标文件内容，提取技术要求：

{file_content}"""


QUALIFICATION_COMPLIANCE_SYSTEM_PROMPT = """你是专业的招标文件审查条款分析师。请提取“资格审查”内容，并按三个模块输出。

请严格使用以下 Markdown 表格格式输出：

## 资格性审查
| 序号 | 资格要求 | 需提供资料 |
| --- | --- | --- |
| 1 | 原文要求 | 原文要求的证明资料 |

## 符合性审查
| 序号 | 资格要求 | 需提供资料 |
| --- | --- | --- |
| 1 | 原文要求 | 原文要求的证明资料 |

## 废标项
| 序号 | 废标项 | 具体表现 |
| --- | --- | --- |
| 1 | 原文废标/否决条款 | 导致废标或无效投标的具体表现 |

要求：
- 尽量按招标文件原文表达提取，不要自行改写成泛泛表述。
- 资格性审查包括供应商资格、资质、业绩、授权、承诺、财务、纳税、社保、信用等门槛条件。
- 符合性审查包括响应文件格式、签章、报价、有效期、实质性响应等要求。
- 废标项包括无效投标、否决投标、一票否决、重大偏差、实质性不响应等条款。
- 每一项资格要求、证明材料或废标情形单独一行；不要把多份材料合并成一个长句反复输出。
- 未发现某个模块内容时，该模块仍保留表头，并写一行“未提及”。"""


QUALIFICATION_COMPLIANCE_USER_PROMPT_TEMPLATE = """请分析以下招标文件内容，提取资格性审查、符合性审查和废标项：

{file_content}"""


PRICE_SCORING_SYSTEM_PROMPT = """你是专业的招标文件评分办法分析师。请提取“评分要求”，分为商务评分和技术评分两个模块。

请严格使用以下 Markdown 表格格式输出：

## 商务评分
| 评分项 | 评分标准 | 分数 |
| --- | --- | --- |
| 原文评分项 | 原文评分标准 | 分值 |

## 技术评分
| 评分项 | 评分标准 | 分数 |
| --- | --- | --- |
| 原文评分项 | 原文评分标准 | 分值 |

要求：
- 商务评分通常包括业绩、资质、信誉、人员、服务能力、企业实力、报价以外的商务响应等。
- 技术评分通常包括技术方案、实施方案、服务方案、质量保障、进度安排、应急方案、售后服务等。
- 表格内容尽量保留招标文件原文表达。
- 如果评分项存在子项，请在“评分项”中体现层级关系。
- 每个评分子项单独一行；如果同一评分项下有多个档位，可以在评分标准中保留档位，但不要重复输出同一评分项。
- 不要输出价格评分，除非招标文件把价格评分归入商务评分且无法拆分；此时请在评分项中标明“价格/报价评分”。
- 未发现某个模块内容时，该模块仍保留表头，并写一行“未提及”。"""


PRICE_SCORING_USER_PROMPT_TEMPLATE = """请分析以下招标文件内容，提取商务评分和技术评分要求：

{file_content}"""


def build_project_overview_messages(file_content: str) -> List[Dict[str, str]]:
    """Build chat messages for extracting a bid project's overview."""
    return [
        {"role": "system", "content": _with_common_rules(PROJECT_OVERVIEW_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": PROJECT_OVERVIEW_USER_PROMPT_TEMPLATE.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_project_overview_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build project overview messages from parsed bid document sections."""
    file_content = sections_to_file_content(sections)
    return build_project_overview_messages(file_content)


def build_technical_scoring_messages(file_content: str) -> List[Dict[str, str]]:
    """Build chat messages for extracting technical requirements."""
    return [
        {"role": "system", "content": _with_common_rules(TECHNICAL_SCORING_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": TECHNICAL_SCORING_USER_PROMPT_TEMPLATE.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_technical_scoring_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build technical requirement messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_technical_scoring_messages(file_content)


def build_qualification_compliance_messages(file_content: str) -> List[Dict[str, str]]:
    """Build messages for extracting qualification/compliance requirements."""
    return [
        {"role": "system", "content": _with_common_rules(QUALIFICATION_COMPLIANCE_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": QUALIFICATION_COMPLIANCE_USER_PROMPT_TEMPLATE.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_qualification_compliance_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build qualification/compliance review messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_qualification_compliance_messages(file_content)


def build_price_scoring_messages(file_content: str) -> List[Dict[str, str]]:
    """Build messages for extracting business and technical scoring."""
    return [
        {"role": "system", "content": _with_common_rules(PRICE_SCORING_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": PRICE_SCORING_USER_PROMPT_TEMPLATE.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_price_scoring_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build scoring requirement messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_price_scoring_messages(file_content)


def extract_project_overview(
    file_content: str,
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract project overview from raw bid document text."""
    return llm_client.think(
        build_project_overview_messages(file_content),
        stream=stream_output,
    ) or ""


def extract_project_overview_from_sections(
    sections: Iterable[Any],
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract project overview from parsed bid document sections."""
    messages = build_project_overview_messages_from_sections(sections)
    return llm_client.think(messages, stream=stream_output) or ""


def extract_technical_scoring_requirements(
    file_content: str,
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract technical requirements from raw bid document text."""
    return llm_client.think(
        build_technical_scoring_messages(file_content),
        stream=stream_output,
    ) or ""


def extract_technical_scoring_requirements_from_sections(
    sections: Iterable[Any],
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract technical requirements from parsed bid document sections."""
    messages = build_technical_scoring_messages_from_sections(sections)
    return llm_client.think(messages, stream=stream_output) or ""


def extract_qualification_compliance_requirements(
    file_content: str,
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract qualification/compliance review requirements from raw text."""
    return llm_client.think(
        build_qualification_compliance_messages(file_content),
        stream=stream_output,
    ) or ""


def extract_qualification_compliance_requirements_from_sections(
    sections: Iterable[Any],
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract qualification/compliance review requirements from parsed sections."""
    messages = build_qualification_compliance_messages_from_sections(sections)
    return llm_client.think(messages, stream=stream_output) or ""


def extract_price_scoring_requirements(
    file_content: str,
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract business and technical scoring requirements from raw text."""
    return llm_client.think(
        build_price_scoring_messages(file_content),
        stream=stream_output,
    ) or ""


def extract_price_scoring_requirements_from_sections(
    sections: Iterable[Any],
    llm_client: Any,
    stream_output: bool = True,
) -> str:
    """Extract business and technical scoring requirements from parsed sections."""
    messages = build_price_scoring_messages_from_sections(sections)
    return llm_client.think(messages, stream=stream_output) or ""


def sections_to_file_content(sections: Iterable[Any]) -> str:
    """Pack parsed sections into one document text for LLM analysis."""
    return "\n\n".join(_section_to_markdown(section) for section in sections).strip()


def _section_to_markdown(section: Any) -> str:
    if isinstance(section, dict):
        title = str(section.get("title") or "").strip()
        markdown = str(section.get("markdown") or section.get("content") or "").strip()
    else:
        title = str(getattr(section, "title", "") or "").strip()
        markdown = str(
            getattr(section, "markdown", "") or getattr(section, "content", "")
        ).strip()

    if markdown.startswith("#") or not title:
        return markdown
    return f"## {title}\n{markdown}".strip()


BUSINESS_CONTENT_SYSTEM_PROMPT_V2 = """你是专业的招投标文件商务条款分析师。请从招标文件内容中提取“商务内容”，重点整理投标报价、合同条款、交付服务、商务响应材料和其他商务关键要求。

输出要求：
- 尽量使用招标文件原文表达，不要自行扩展、推断或编造。
- 如果招标文件中没有明确提到某项内容，请写“未明确”。
- 如果某项内容存在多个条款，请合并整理，但保留关键原文信息、数值、期限、比例和限制条件。
- 只提取商务内容，不要输出技术要求、资格审查、商务评分、技术评分或价格评分。
- 使用 Markdown 表格，严格按以下结构输出：
- 每个二级标题下面必须是 Markdown 表格，不要用项目符号列表、普通段落、JSON 或代码块替代表格。
- 表格分隔行必须使用 `| --- | --- |`，确保前端可以渲染为表格。
- 对投标文件材料、承诺函、声明函、偏离表、报价表等材料清单，应一项材料一行，不要把多个材料名称堆在同一个单元格里。
- 对金额、比例、期限、地点、付款节点等关键商务条件，应尽量拆成独立行，便于后续入库和核对。

# 商务内容

## 一、投标报价要求
| 项目 | 内容 |
| --- | --- |
| 报价方式 | |
| 报价范围 | |
| 最高限价/预算限制 | |
| 分项报价要求 | |
| 费用包含范围 | |
| 报价无效情形 | |

## 二、合同条款要求
| 项目 | 内容 |
| --- | --- |
| 合同签订要求 | |
| 履行期限 | |
| 履行地点 | |
| 付款方式 | |
| 付款节点/比例 | |
| 验收方式 | |
| 违约责任 | |
| 争议解决 | |

## 三、交付与服务要求
| 项目 | 内容 |
| --- | --- |
| 交付时间 | |
| 交付地点 | |
| 交付方式 | |
| 服务期限 | |
| 售后服务 | |
| 培训要求 | |
| 运维/质保/维保要求 | |

## 四、投标文件商务响应要求
| 材料/要求 | 具体内容 |
| --- | --- |
| 商务偏离表 | |
| 报价表 | |
| 分项报价表 | |
| 授权/承诺/声明文件 | |
| 投标保证金 | |
| 履约保证金 | |
| 其他商务材料 | |

## 五、其他商务关键要求
| 项目 | 内容 |
| --- | --- |
| 联合体投标 | |
| 转包/分包 | |
| 进口产品 | |
| 中小企业采购 | |
| 政策优惠 | |
| 其他关键要求 | |"""


BUSINESS_CONTENT_USER_PROMPT_TEMPLATE_V2 = """请分析以下招标文件内容，提取商务内容：

{file_content}"""


BUSINESS_SCORING_SYSTEM_PROMPT_V2 = """你是专业的招标文件评分办法分析师。请从招标文件中提取“商务评分”和“技术评分”。

请严格输出以下两个 Markdown 表格：

## 商务评分
| 评分项 | 评分标准 | 分数 |
| --- | --- | --- |
| 原文评分项 | 原文评分标准、得分条件、证明材料、扣分/不得分条件 | 分值 |

## 技术评分
| 评分项 | 评分标准 | 分数 |
| --- | --- | --- |
| 原文评分项 | 原文评分标准、得分条件、证明材料、扣分/不得分条件 | 分值 |

要求：
- 商务评分通常包括业绩、资质、信誉、人员、服务能力、企业实力、类似项目经验、认证证书、商务响应等。
- 技术评分通常包括技术方案、实施方案、服务方案、质量保障、进度安排、应急方案、售后服务、培训方案等。
- 商务评分和技术评分必须分开，不要把技术方案类评分放入商务评分。
- “评分标准”中保留原文的档位、条件、证明材料、扣分/不得分规则。
- “分数”中保留原文分值，如“5分”“0-3分”“最高10分”；未明确写“未明确”。
- 每个评分子项单独一行；不要将同一证明材料或评分项重复列出。
- 不要输出价格评分，除非招标文件把价格评分归入商务评分且无法拆分；此时在评分项中标明“价格/报价评分”。
- 未发现某个模块内容时，该模块仍保留表头，并写一行“未提及”。
- 不要编造招标文件未写明的评分项。"""


BUSINESS_SCORING_USER_PROMPT_TEMPLATE_V2 = """请分析以下招标文件内容，提取商务评分和技术评分要求：

{file_content}"""


def build_business_content_messages(file_content: str) -> List[Dict[str, str]]:
    """Build messages for extracting business content."""
    return [
        {"role": "system", "content": _with_common_rules(BUSINESS_CONTENT_SYSTEM_PROMPT_V2)},
        {
            "role": "user",
            "content": BUSINESS_CONTENT_USER_PROMPT_TEMPLATE_V2.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_business_content_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build business content messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_business_content_messages(file_content)


def build_business_scoring_messages(file_content: str) -> List[Dict[str, str]]:
    """Build messages for extracting business and technical scoring."""
    return [
        {"role": "system", "content": _with_common_rules(BUSINESS_SCORING_SYSTEM_PROMPT_V2)},
        {
            "role": "user",
            "content": BUSINESS_SCORING_USER_PROMPT_TEMPLATE_V2.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_business_scoring_messages_from_sections(
    sections: Iterable[Any],
) -> List[Dict[str, str]]:
    """Build scoring messages from parsed sections."""
    file_content = sections_to_scoring_context(sections)
    return build_business_scoring_messages(file_content)


SCORING_CONTEXT_KEYWORDS = (
    "评分",
    "评审",
    "评标",
    "评审因素",
    "评分标准",
    "评分办法",
    "评分细则",
    "详细评审",
    "综合评分",
    "商务评分",
    "商务评审",
    "商务部分",
    "资信评分",
    "资信部分",
    "企业实力",
    "业绩",
    "技术评分",
    "技术评审",
    "技术部分",
    "技术方案",
    "实施方案",
    "服务方案",
    "分值",
    "得分",
    "满分",
    "扣分",
    "不得分",
)


def sections_to_scoring_context(
    sections: Iterable[Any],
    window: int = 2,
    max_chars: int = 36000,
) -> str:
    """Extract scoring-related sections and nearby context before asking the LLM."""
    section_texts = [_section_to_markdown(section).strip() for section in sections]
    section_texts = [text for text in section_texts if text]
    if not section_texts:
        return ""

    hit_indexes = [
        index
        for index, text in enumerate(section_texts)
        if any(keyword in text for keyword in SCORING_CONTEXT_KEYWORDS)
    ]
    if not hit_indexes:
        return "\n\n".join(section_texts)[-max_chars:]

    selected_indexes = set()
    for index in hit_indexes:
        start = max(0, index - window)
        end = min(len(section_texts), index + window + 1)
        selected_indexes.update(range(start, end))

    selected_texts = [section_texts[index] for index in sorted(selected_indexes)]
    context = "\n\n".join(selected_texts).strip()
    if len(context) <= max_chars:
        return context

    scoring_lines = [
        line
        for line in context.splitlines()
        if any(keyword in line for keyword in SCORING_CONTEXT_KEYWORDS)
        or line.strip().startswith(("|", "#"))
    ]
    compressed = "\n".join(scoring_lines).strip()
    return (compressed or context)[-max_chars:]


GLOBAL_CONTEXT_SYSTEM_PROMPT = """你是招投标文件结构还原与项目画像分析师。
本轮只做两件事：
1. 输出完整 project_profile，提取项目名称、项目编号、预算/最高限价、招标人/采购人、招标代理机构、采购方式、是否分包/包号、项目类别、服务/履约期限、中小企业预留、暗标、代理商投标、联合体投标、各种时间安排等项目基本信息。
2. 输出全文 section_tree，尽量还原章节标题、层级关系、起始位置/页码、结束位置/页码、标题路径和该章节可能对应的抽取模块。

必须严格输出 JSON，不要输出 Markdown、解释、寒暄或代码块。JSON 结构如下：
{
  "project_profile": {
    "project_name": "",
    "project_code": "",
    "budget_text": "",
    "buyer_name": "",
    "agency_name": "",
    "procurement_method": "",
    "package_info": "",
    "project_category": "",
    "service_period": "",
    "is_sme_reserved": "",
    "is_blind_bid": "",
    "is_agent_bid_allowed": "",
    "is_consortium_bid_allowed": "",
    "key_dates": "",
    "all_time_arrangements": "",
    "implementation_scope": "",
    "technical_features": "",
    "other_key_requirements": ""
  },
  "section_tree": [
    {
      "section_index": 1,
      "title": "",
      "level": 1,
      "title_path": "",
      "start_position": "",
      "end_position": "",
      "module_hint": "",
      "summary": ""
    }
  ]
}

要求：
- 不要编造原文未写明的信息；没有明确依据时写“未提及”。
- is_sme_reserved、is_blind_bid、is_agent_bid_allowed、is_consortium_bid_allowed 只能填“是”或“否”；原文未提及或无法判断时一律填“否”。
- all_time_arrangements 需要汇总招标文件中出现的各种时间节点，包括网上报名、获取文件、澄清答疑、投标截止、开标、保证金、项目实施/交付/服务等时间。
- section_tree 必须覆盖用户提供的全部章节目录线索，不能只列你认为重要的章节。
- module_hint 可填写 project_overview、business_content、technical_requirements、qualification_compliance、scoring、other。
"""


GLOBAL_CONTEXT_USER_PROMPT_TEMPLATE = """请基于以下统一中间格式，提取 project_profile 并还原 section_tree。

【统一中间格式】
{file_content}"""


SPECIALIST_CONTEXT_RULES = """专项抽取约束：
- 下方“全局项目信息和章节树”只作为上下文锚点，专项抽取不得修改 project_profile 中的项目基本信息。
- 只能从“指定候选章节内容”中提取当前模块信息；如果候选章节不足，请写“未提及”，不要从全局章节树中脑补。
- 输出中尽量保留原文关键数值、期限、比例、材料名称、评分分值和否决条件。
"""


PROJECT_OVERVIEW_FIELDS = [
    ("项目名称", "project_name"),
    ("项目编号", "project_code"),
    ("项目类别（服务类，货物类，工程类）和服务年限", "project_category"),
    ("包号", "package_info"),
    ("项目规模和预算", "budget_text"),
    ("招标人", "buyer_name"),
    ("招标代理机构", "agency_name"),
    ("项目所属领域", "project_domain"),
    ("各种时间安排", "all_time_arrangements"),
    ("项目要实施的具体内容", "implementation_scope"),
    ("主要技术特点", "technical_features"),
    ("其他关键要求", "other_key_requirements"),
    ("是否专门面向中小微企业采购", "is_sme_reserved"),
    ("是否为暗标", "is_blind_bid"),
    ("是否允许代理商投标", "is_agent_bid_allowed"),
    ("是否允许联合体投标", "is_consortium_bid_allowed"),
]


def build_global_context_messages(file_content: str) -> List[Dict[str, str]]:
    """Build first-pass messages for project profile and document tree."""
    return [
        {"role": "system", "content": GLOBAL_CONTEXT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": GLOBAL_CONTEXT_USER_PROMPT_TEMPLATE.format(
                file_content=file_content.strip()
            ),
        },
    ]


def build_global_context_messages_from_sections(
    sections: Iterable[Any],
    max_chars: int = 70000,
) -> List[Dict[str, str]]:
    """Build global context messages from all parsed sections."""
    file_content = sections_to_file_content(sections)
    if len(file_content) > max_chars:
        file_content = file_content[:max_chars].rstrip()
    return build_global_context_messages(file_content)


def build_project_overview_text_from_global_context(global_context: str) -> str:
    """Convert global project JSON into the existing overview text shape."""
    payload = _load_global_context_json(global_context)
    profile = payload.get("project_profile") if isinstance(payload, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    lines = []
    for label, key in PROJECT_OVERVIEW_FIELDS:
        value = profile.get(key) or ("否" if label.startswith("是否") else "未提及")
        if label == "各种时间安排" and value == "未提及":
            value = profile.get("key_dates") or "未提及"
        lines.append(f"{label}：{value}")
    return "\n".join(lines)


def format_global_context_for_specialist(global_context: str, max_chars: int = 18000) -> str:
    """Compact global context before adding it to specialist extraction prompts."""
    text = (global_context or "").strip()
    if not text:
        return "未生成全局上下文。"
    payload = _load_global_context_json(text)
    if payload:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n...（全局上下文已截断）"
    return text


def _load_global_context_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def _pack_specialist_user_prompt(
    template: str,
    file_content: str,
    global_context: str | None = None,
) -> str:
    file_content = (file_content or "").strip()
    if not global_context:
        return template.format(file_content=file_content)
    return (
        f"{SPECIALIST_CONTEXT_RULES}\n\n"
        "【全局项目信息和章节树】\n"
        f"{format_global_context_for_specialist(global_context)}\n\n"
        "【指定候选章节内容】\n"
        f"{template.format(file_content=file_content)}"
    )


def build_technical_scoring_messages(
    file_content: str,
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build chat messages for extracting technical requirements."""
    return [
        {"role": "system", "content": _with_common_rules(TECHNICAL_SCORING_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": _pack_specialist_user_prompt(
                TECHNICAL_SCORING_USER_PROMPT_TEMPLATE,
                file_content,
                global_context,
            ),
        },
    ]


def build_technical_scoring_messages_from_sections(
    sections: Iterable[Any],
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build technical requirement messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_technical_scoring_messages(file_content, global_context=global_context)


def build_qualification_compliance_messages(
    file_content: str,
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build messages for extracting qualification/compliance requirements."""
    return [
        {"role": "system", "content": _with_common_rules(QUALIFICATION_COMPLIANCE_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": _pack_specialist_user_prompt(
                QUALIFICATION_COMPLIANCE_USER_PROMPT_TEMPLATE,
                file_content,
                global_context,
            ),
        },
    ]


def build_qualification_compliance_messages_from_sections(
    sections: Iterable[Any],
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build qualification/compliance review messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_qualification_compliance_messages(file_content, global_context=global_context)


def build_business_content_messages(
    file_content: str,
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build messages for extracting business content."""
    return [
        {"role": "system", "content": _with_common_rules(BUSINESS_CONTENT_SYSTEM_PROMPT_V2)},
        {
            "role": "user",
            "content": _pack_specialist_user_prompt(
                BUSINESS_CONTENT_USER_PROMPT_TEMPLATE_V2,
                file_content,
                global_context,
            ),
        },
    ]


def build_business_content_messages_from_sections(
    sections: Iterable[Any],
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build business content messages from parsed sections."""
    file_content = sections_to_file_content(sections)
    return build_business_content_messages(file_content, global_context=global_context)


def build_business_scoring_messages(
    file_content: str,
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build messages for extracting business and technical scoring."""
    return [
        {"role": "system", "content": _with_common_rules(BUSINESS_SCORING_SYSTEM_PROMPT_V2)},
        {
            "role": "user",
            "content": _pack_specialist_user_prompt(
                BUSINESS_SCORING_USER_PROMPT_TEMPLATE_V2,
                file_content,
                global_context,
            ),
        },
    ]


def build_business_scoring_messages_from_sections(
    sections: Iterable[Any],
    global_context: str | None = None,
) -> List[Dict[str, str]]:
    """Build scoring messages from parsed sections."""
    file_content = sections_to_scoring_context(sections)
    return build_business_scoring_messages(file_content, global_context=global_context)
