from energy.facts.repository import Fact
from energy.facts.warehouse import RegionalWarehouse
from energy.intake.scope import normalize_business_day


def read_current(warehouse: RegionalWarehouse, region: str,
                 business_day: str) -> tuple[Fact, ...]:
    warehouse.scope.require_region(region)
    return warehouse.facts.list_effective(normalize_business_day(business_day))
