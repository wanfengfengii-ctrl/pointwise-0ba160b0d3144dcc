from energy.facts.warehouse import RegionalWarehouse
from energy.intake.receipt import ReceivedBatch
from energy.storage import DomainError


def read_batch(warehouse: RegionalWarehouse, receipt_number: str) -> ReceivedBatch:
    warehouse.scope.require_local_reference('batch', receipt_number)
    batch = warehouse.batches.find_by_receipt(receipt_number)
    if batch is None:
        raise DomainError('unknown_batch', f'unknown receipt {receipt_number}')
    return batch
