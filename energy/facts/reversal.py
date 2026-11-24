from energy.facts.repository import ReversalReceipt
from energy.facts.warehouse import RegionalWarehouse
from energy.storage import require_text


def reverse_usage(warehouse: RegionalWarehouse, region: str, request_number: str,
                  fact_number: str) -> ReversalReceipt:
    warehouse.scope.require_region(region)
    warehouse.scope.require_local_reference('fact', fact_number)
    require_text(request_number, 'reversal request number')
    return warehouse.facts.commit_reversal(request_number, fact_number)
