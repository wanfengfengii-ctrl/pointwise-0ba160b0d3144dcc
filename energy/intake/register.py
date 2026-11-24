from collections.abc import Iterable

from energy.facts.warehouse import RegionalWarehouse
from energy.intake.receipt import BatchReceipt
from energy.intake.rows import SourceRow, normalize_rows
from energy.intake.scope import normalize_business_day
from energy.storage import require_text


def receive_batch(
    warehouse: RegionalWarehouse, region: str, business_day: str,
    batch_number: str, rows: Iterable[SourceRow],
) -> BatchReceipt:
    warehouse.scope.require_region(region)
    day = normalize_business_day(business_day)
    require_text(batch_number, 'batch number')
    return warehouse.batches.store_once(batch_number, day, normalize_rows(rows))
