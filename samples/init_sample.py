from argparse import ArgumentParser
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from energy.facts.warehouse import RegionalWarehouse, initialize_warehouse, open_warehouse
from energy.reports.repository import ReportRepository
from energy.versions.repository import VersionRepository


@dataclass(slots=True)
class SampleStores:
    versions: VersionRepository
    reports: ReportRepository
    warehouses: dict[str, RegionalWarehouse]


@contextmanager
def open_stores(root: Path, *, initialize: bool = False):
    if initialize:
        root.mkdir(parents=True, exist_ok=True)
    catalog = root / 'catalog.sqlite3'
    with ExitStack() as stack:
        versions = VersionRepository(catalog)
        stack.callback(versions.close)
        reports = ReportRepository(catalog)
        stack.callback(reports.close)
        if initialize:
            versions.initialize()
            reports.initialize()
        open_region = initialize_warehouse if initialize else open_warehouse
        warehouses = {}
        for region in ('east', 'west'):
            warehouse = open_region(root / f'{region}.sqlite3', region)
            stack.callback(warehouse.close)
            warehouses[region] = warehouse
        yield SampleStores(versions, reports, warehouses)


def main() -> None:
    parser = ArgumentParser(description='Initialize the three energy warehouse databases.')
    parser.add_argument('directory', type=Path)
    arguments = parser.parse_args()
    with open_stores(arguments.directory, initialize=True):
        pass


if __name__ == '__main__':
    main()
