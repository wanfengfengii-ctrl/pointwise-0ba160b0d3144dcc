from energy.facts.repository import FactReceipt
from energy.facts.warehouse import RegionalWarehouse
from energy.storage import require_text


def post_usage(warehouse: RegionalWarehouse, region: str, request_number: str,
               preview_number: str) -> FactReceipt:
    warehouse.scope.require_region(region)
    warehouse.scope.require_local_reference('preview', preview_number)
    require_text(request_number, 'posting request number')
    return warehouse.facts.commit_post(request_number, preview_number)
