# -*- coding: utf-8 -*-
"""Export SQLite table structures to an Excel-compatible .xlsx file."""

from __future__ import annotations

import html
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from bid_agent.infrastructure.database import DB_PATH, init_database  # noqa: E402


OUTPUT_PATH = ROOT / "docs" / "database" / "招投标智能体数据库表结构.xlsx"
DESIGN_DOC_PATH = ROOT / "docs" / "database" / "schema-design.md"


TABLE_DESCRIPTIONS = {
    "projects": "项目主表，保存一个招投标项目的基础信息。",
    "source_documents": "文件主表，保存招标文件、投标文件、合同、附件等原始文件信息。",
    "document_sections": "文档章节表，保存解析后的标题层级、页码范围和章节 Markdown。",
    "document_chunks": "RAG 切片表，保存用于检索、引用和生成的语义切片。",
    "chunk_embeddings": "向量索引表，记录切片向量化后的索引信息。",
    "extraction_runs": "抽取任务表，记录每次解析、抽取、审查或复核任务。",
    "project_profile": "项目概览表，保存投标人须知和项目基本字段。",
    "qualification_requirements": "资格审查表，保存资格性审查和符合性审查条款。",
    "rejection_items": "废标项表，保存无效投标、否决投标和重大偏差风险条款。",
    "business_requirements": "商务要求表，保存报价、合同、付款、交付、验收等商务条款。",
    "technical_requirements": "技术要求表，保存技术参数、服务要求、验收标准等。",
    "scoring_items": "评分项表，保存商务评分、技术评分、价格评分等评分标准。",
    "review_findings": "审查发现表，保存内容审查、废标风险和一致性检查发现。",
    "knowledge_entries": "知识库通用表，保存前端知识库八类知识资产。",
    "companies": "公司信息表，保存投标主体基础信息。",
    "company_qualifications": "资质管理表，保存营业执照、体系认证、授权文件等。",
    "company_personnel": "人员信息表，保存项目经理、技术负责人和团队成员信息。",
    "financial_records": "财务信息表，保存审计报告、纳税社保、银行资信等。",
    "performance_records": "业绩信息表，保存历史项目业绩和证明材料信息。",
    "historical_cases": "历史案例库表，保存投标复盘、相似项目和风险处理经验。",
    "historical_bid_files": "历史投标文件表，保存商务标、技术标、响应表等文件索引。",
    "solution_materials": "方案素材库表，保存可复用的技术方案、商务响应和服务方案素材。",
    "bid_generation_tasks": "标书生成任务表，记录商务标、技术标、审查报告等生成任务。",
}


FIELD_DESCRIPTIONS = {
    "id": "主键 ID，系统生成。",
    "project_id": "所属项目 ID，关联 projects.id。",
    "document_id": "所属文件 ID，关联 source_documents.id。",
    "section_id": "来源章节 ID。",
    "chunk_id": "来源切片 ID，关联 document_chunks.id。",
    "created_at": "创建时间，ISO 字符串。",
    "updated_at": "更新时间，ISO 字符串。",
    "confirmed_status": "人工确认状态，如未确认、已确认、需复核。",
    "source_text": "原文证据片段，用于回溯和审查。",
    "status": "业务状态。",
    "tags_json": "JSON 字符串，保存标签列表。",
    "metadata_json": "JSON 字符串，保存扩展元数据。",
    "title": "标题或名称。",
    "content": "正文内容。",
    "notes": "备注或使用建议。",
    "file_path": "本地文件路径或附件路径。",
    "file_name": "文件名称。",
    "file_ext": "文件扩展名。",
    "parse_method": "实际使用的解析方式。",
    "parse_status": "解析状态。",
    "project_name": "项目名称。",
    "project_code": "项目编号、招标编号或采购编号。",
    "buyer_name": "招标人或采购人。",
    "agency_name": "招标代理机构。",
    "budget_amount": "预算金额数值。",
    "requirement_text": "条款或要求正文。",
    "requirement_type": "要求类型。",
    "review_type": "审查类型。",
    "risk_level": "风险等级。",
    "score_type": "评分类型，如商务评分、技术评分。",
    "score_value": "标准化后的分值。",
    "score_text": "分值原文。",
}


def main() -> None:
    init_database()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        table_names = [
            row["name"]
            for row in conn.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
            )
        ]
        workbook = build_workbook(conn, table_names)

    write_xlsx(OUTPUT_PATH, workbook)
    print(OUTPUT_PATH)


def build_workbook(conn: sqlite3.Connection, table_names: list[str]) -> list[tuple[str, list[list[object]]]]:
    design_fields = load_design_fields()
    sheets: list[tuple[str, list[list[object]]]] = []
    summary_rows = [["序号", "表名", "表说明", "落库字段数", "设计字段数", "当前记录数"]]
    field_headers = [
        "字段序号",
        "字段名",
        "设计类型",
        "SQLite类型",
        "必填",
        "是否主键",
        "是否非空",
        "默认值",
        "字段含义",
        "口径",
        "格式 / 示例",
        "落库状态",
    ]
    all_fields = [["表名", *field_headers]]

    for index, table_name in enumerate(table_names, start=1):
        columns = conn.execute(f"pragma table_info({quote_identifier(table_name)})").fetchall()
        count = conn.execute(f"select count(*) as count from {quote_identifier(table_name)}").fetchone()["count"]
        table_design = design_fields.get(table_name, {})
        sqlite_columns = {col["name"]: col for col in columns}
        ordered_field_names = [col["name"] for col in columns]
        ordered_field_names.extend(name for name in table_design if name not in sqlite_columns)
        summary_rows.append([
            index,
            table_name,
            TABLE_DESCRIPTIONS.get(table_name, ""),
            len(columns),
            len(table_design),
            count,
        ])

        table_rows = [field_headers]
        for field_index, field_name in enumerate(ordered_field_names, start=1):
            col = sqlite_columns.get(field_name)
            design = table_design.get(field_name, {})
            design_type = design.get("类型") or (col["type"] if col else "")
            sqlite_type = col["type"] if col else ""
            required = design.get("必填") or ("是" if col and (col["pk"] or col["notnull"]) else "否")
            field_meaning = design.get("含义") or describe_field(field_name)
            caliber = design.get("口径", "")
            example = design.get("格式 / 示例") or design.get("格式/示例", "")
            row = [
                field_index,
                field_name,
                design_type,
                sqlite_type,
                required,
                "是" if col and col["pk"] else "否",
                "是" if col and col["notnull"] else "否",
                "" if not col or col["dflt_value"] is None else col["dflt_value"],
                field_meaning,
                caliber,
                example,
                "已落库" if col else "设计未落库",
            ]
            table_rows.append(row)
            all_fields.append([table_name, *row])

        sheets.append((safe_sheet_name(table_name), table_rows))

    return [("目录", summary_rows), ("全部字段", all_fields), *sheets]


def load_design_fields() -> dict[str, dict[str, dict[str, str]]]:
    """Read field meanings/calibers/examples from DATABASE_SCHEMA_DESIGN.md."""
    if not DESIGN_DOC_PATH.exists():
        return {}

    tables: dict[str, dict[str, dict[str, str]]] = {}
    current_table = ""
    headers: list[str] = []
    in_field_table = False

    for raw_line in DESIGN_DOC_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        table_match = re.match(r"^##\s+\d+\.\s+`([^`]+)`", line)
        if table_match:
            current_table = table_match.group(1)
            tables.setdefault(current_table, {})
            headers = []
            in_field_table = False
            continue

        if not current_table:
            continue

        if not line.startswith("|"):
            if in_field_table and not line:
                headers = []
                in_field_table = False
            continue

        cells = split_markdown_row(line)
        if not cells:
            continue

        if "字段名" in cells and "类型" in cells:
            headers = cells
            in_field_table = True
            continue

        if not in_field_table or is_markdown_separator(cells):
            continue

        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        field_name = normalize_markdown_cell(row.get("字段名", ""))
        if field_name:
            tables.setdefault(current_table, {})[field_name] = {
                normalize_markdown_cell(key): normalize_markdown_cell(value)
                for key, value in row.items()
            }

    return tables


def split_markdown_row(line: str) -> list[str]:
    return [normalize_markdown_cell(cell) for cell in line.strip().strip("|").split("|")]


def normalize_markdown_cell(value: str) -> str:
    value = value.strip()
    value = value.replace("`", "")
    value = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    return re.sub(r"\s+", " ", value).strip()


def is_markdown_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def describe_field(field_name: str) -> str:
    if field_name in FIELD_DESCRIPTIONS:
        return FIELD_DESCRIPTIONS[field_name]
    if field_name.endswith("_json"):
        return "JSON 字符串字段。"
    if field_name.endswith("_at"):
        return "时间字段，ISO 字符串。"
    if field_name.endswith("_id"):
        return "关联 ID 字段。"
    if "amount" in field_name:
        return "金额数值字段。"
    if "date" in field_name:
        return "日期或时间文本字段。"
    if "text" in field_name:
        return "文本内容字段。"
    return ""


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
    sheet_xmls = []
    for sheet_id, (_, rows) in enumerate(sheets, start=1):
        sheet_xmls.append((sheet_id, render_sheet_xml(rows)))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", render_content_types(len(sheets)))
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("xl/workbook.xml", render_workbook_xml([name for name, _ in sheets]))
        zf.writestr("xl/_rels/workbook.xml.rels", render_workbook_rels(len(sheets)))
        zf.writestr("xl/styles.xml", STYLES_XML)
        for sheet_id, xml in sheet_xmls:
            zf.writestr(f"xl/worksheets/sheet{sheet_id}.xml", xml)


def render_sheet_xml(rows: list[list[object]]) -> str:
    xml_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell_ref = f"{column_name(col_index)}{row_index}"
            text = html.escape(str(value), quote=False)
            style = ' s="1"' if row_index == 1 else ""
            cells.append(f'<c r="{cell_ref}" t="inlineStr"{style}><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols><col min="1" max="20" width="24" customWidth="1"/></cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def render_content_types(sheet_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{overrides}</Types>"
    )


def render_workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{html.escape(name, quote=True)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def render_workbook_rels(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1)
    )
    rels += (
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}</Relationships>"
    )


def column_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def safe_sheet_name(name: str) -> str:
    for char in "[]:*?/\\'":
        name = name.replace(char, "_")
    return name[:31] or "Sheet"


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)

STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font>'
    '<font><b/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


if __name__ == "__main__":
    main()
