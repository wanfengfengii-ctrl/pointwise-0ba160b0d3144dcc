from collections.abc import Iterable
from dataclasses import dataclass

from energy.storage import DomainError, decode_integer, encode_integer, require_text


@dataclass(frozen=True, slots=True)
class SourceRow:
    row_number: int
    device: str
    input_unit: str
    reading: int | None
    source: str


def normalize_rows(rows: Iterable[SourceRow]) -> tuple[SourceRow, ...]:
    try:
        entries = iter(rows)
    except TypeError as error:
        raise DomainError('invalid_row', 'source rows must be iterable') from error
    accepted = []
    seen = set()
    for row in entries:
        if not isinstance(row, SourceRow) or type(row.row_number) is not int:
            raise DomainError('invalid_row', 'source rows require an integer row number')
        if row.row_number in seen:
            raise DomainError('duplicate_row', f'duplicate original row {row.row_number}')
        if row.reading is not None and type(row.reading) is not int:
            raise DomainError('invalid_row', 'reading must be an integer or None')
        require_text(row.device, 'device', code='invalid_row')
        require_text(row.input_unit, 'input unit', code='invalid_row')
        require_text(row.source, 'row source', code='invalid_row')
        accepted.append(row)
        seen.add(row.row_number)
    return tuple(accepted)


def encode_source(row: SourceRow) -> tuple[str, str, str, str | None, str]:
    reading = None if row.reading is None else encode_integer(row.reading)
    return encode_integer(row.row_number), row.device, row.input_unit, reading, row.source


def decode_source(
    row_number: str, device: str, input_unit: str, reading: str | None, source: str
) -> SourceRow:
    return SourceRow(
        decode_integer(row_number), device, input_unit,
        None if reading is None else decode_integer(reading), source,
    )
