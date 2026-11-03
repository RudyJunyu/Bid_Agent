from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CheckContext:
    project_id: str
    requirements: list[dict] = field(default_factory=list)
    bid_sections: list[dict] = field(default_factory=list)
    outline_markdown: str = ''
    bid_text: str = ''
    use_llm: bool = False
    llm: Any = None


@dataclass
class CheckFinding:
    check_name: str
    severity: str
    title: str
    detail: str
    requirement_item_id: str | None = None
    section_key: str | None = None
    evidence: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'check_name': self.check_name,
            'severity': self.severity,
            'title': self.title,
            'detail': self.detail,
            'requirement_item_id': self.requirement_item_id,
            'section_key': self.section_key,
            'evidence': self.evidence,
        }


CheckFn = Callable[[CheckContext], list[CheckFinding]]
