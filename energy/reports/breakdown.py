from fractions import Fraction

from energy.conversion.units import OUTPUT_UNIT
from energy.facts.repository import Fact
from energy.reports.snapshot import ReportFact, ReportLine, ReportSnapshot


def build_breakdown(number: str, region: str, business_day: str,
                    facts: tuple[Fact, ...]) -> ReportSnapshot:
    total = Fraction(0)
    missing_count = 0
    report_facts = []
    for fact in facts:
        preview = fact.preview
        lines = []
        for line in preview.lines:
            if line.quantity is None:
                missing_count += 1
            else:
                total += line.quantity
            lines.append(ReportLine(line.position, line.source, line.coefficient,
                                    line.rule_source, line.quantity))
        report_facts.append(ReportFact(
            fact.fact_number, fact.sequence, preview.number, preview.version_number,
            preview.batch_number, preview.receipt_number, tuple(lines),
        ))
    return ReportSnapshot(number, region, business_day, OUTPUT_UNIT,
                          total, missing_count, tuple(report_facts))
