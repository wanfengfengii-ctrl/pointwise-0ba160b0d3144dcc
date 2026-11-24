from energy.reports.repository import ReportRepository
from energy.reports.snapshot import ReportSnapshot
from energy.storage import DomainError, require_text


def get_report(repository: ReportRepository, report_number: str) -> ReportSnapshot:
    require_text(report_number, 'report number')
    snapshot = repository.find(report_number)
    if snapshot is None:
        raise DomainError('unknown_report', f'unknown report {report_number}')
    return snapshot
