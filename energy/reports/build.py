from energy.facts.current import read_current
from energy.facts.warehouse import RegionalWarehouse
from energy.intake.scope import normalize_business_day
from energy.reports.breakdown import build_breakdown
from energy.reports.repository import ReportRepository, require_same_binding
from energy.reports.snapshot import ReportSnapshot
from energy.storage import require_text


def freeze_report(repository: ReportRepository, warehouse: RegionalWarehouse,
                  report_number: str, region: str, business_day: str) -> ReportSnapshot:
    require_text(report_number, 'report number')
    warehouse.scope.require_region(region)
    day = normalize_business_day(business_day)
    stored = repository.find(report_number)
    if stored is not None:
        require_same_binding(stored, region, day)
        return stored

    facts = read_current(warehouse, region, day)
    return repository.store_once(build_breakdown(report_number, region, day, facts))
