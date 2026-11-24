from energy.intake.rows import SourceRow
from energy.storage import DomainError
from energy.versions.rules import DeviceRule


OUTPUT_UNIT = 'kWh'


def require_matching_unit(row: SourceRow, rule: DeviceRule) -> None:
    if row.input_unit != rule.input_unit:
        raise DomainError(
            'unit_mismatch',
            f'row {row.row_number} for {row.device} uses {row.input_unit}; expected {rule.input_unit}',
        )
