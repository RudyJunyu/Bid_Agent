"""Registry-driven compliance run."""
from __future__ import annotations

from bid_agent.compliance import checks
from bid_agent.compliance.types import CheckContext, CheckFinding, CheckFn

CHECKER_VERSION = 'compliance-v3'

RULE_CHECKS: list[tuple[str, CheckFn]] = [
    ('pricing_check', checks.pricing_check),
    ('rejection_alignment', checks.rejection_alignment_check),
    ('mandatory_req_check', checks.mandatory_star_check),
    ('score_coverage', checks.scoring_coverage_check),
    ('response_matrix', checks.response_matrix_check),
    ('expired_asset', checks.expired_asset_check),
    ('selfcheck_list', checks.selfcheck_list),
]

LLM_CHECKS: list[tuple[str, CheckFn]] = [
    ('disqualification_check', checks.llm_disqualification_check),
]


def run_checks(ctx: CheckContext) -> tuple[list[CheckFinding], dict]:
    findings: list[CheckFinding] = []
    for _, fn in RULE_CHECKS:
        findings.extend(fn(ctx))
    if ctx.use_llm:
        for _, fn in LLM_CHECKS:
            findings.extend(fn(ctx))
    summary = checks.risk_score(findings)
    summary['checker_version'] = CHECKER_VERSION
    summary['finding_count'] = len(findings)
    summary['open_critical'] = sum(
        1 for item in findings if item.severity in {'critical', 'high'}
    )
    return findings, summary
