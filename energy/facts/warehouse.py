from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from energy.conversion.repository import PreviewRepository
from energy.facts.repository import FactRepository
from energy.intake.receipt import BatchRepository
from energy.intake.scope import WarehouseScope
from energy.storage import CommitHook, DomainError, open_database, transaction


@dataclass(slots=True)
class RegionalWarehouse:
    scope: WarehouseScope
    batches: BatchRepository
    previews: PreviewRepository
    facts: FactRepository
    _db: sqlite3.Connection = field(repr=False)

    def close(self) -> None:
        self._db.close()


def _assemble(connection: sqlite3.Connection, scope: WarehouseScope,
              before_commit: CommitHook | None) -> RegionalWarehouse:
    batches = BatchRepository(connection, scope)
    previews = PreviewRepository(connection, scope)
    facts = FactRepository(connection, scope, previews, before_commit)
    return RegionalWarehouse(scope, batches, previews, facts, connection)


def _stored_region(connection: sqlite3.Connection) -> str | None:
    table = connection.execute('''
        SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'warehouse_identity'
    ''').fetchone()
    if table is None:
        return None
    identity = connection.execute('SELECT region FROM warehouse_identity WHERE singleton = 1').fetchone()
    return None if identity is None else identity['region']


def initialize_warehouse(path: str | Path, region: str, *,
                         before_commit: CommitHook | None = None) -> RegionalWarehouse:
    scope = WarehouseScope(region)
    connection = open_database(path)
    try:
        warehouse = _assemble(connection, scope, before_commit)
        with transaction(connection, write=True):
            stored = _stored_region(connection)
            if stored is None:
                existing = connection.execute('''
                    SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ''').fetchall()
                if existing:
                    raise DomainError('unbound_warehouse', 'warehouse identity is missing from a nonempty database')
                connection.execute('''
                    CREATE TABLE warehouse_identity (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1), region TEXT NOT NULL
                    )
                ''')
                connection.execute('INSERT INTO warehouse_identity VALUES (1, ?)', (region,))
            else:
                scope.require_region(stored)
            warehouse.batches.initialize()
            warehouse.previews.initialize()
            warehouse.facts.initialize()
    except BaseException:
        connection.close()
        raise
    return warehouse


def open_warehouse(path: str | Path, region: str, *,
                   before_commit: CommitHook | None = None) -> RegionalWarehouse:
    scope = WarehouseScope(region)
    connection = open_database(path, create=False)
    try:
        stored = _stored_region(connection)
        if stored is None:
            raise DomainError('unbound_warehouse', 'database has no warehouse identity')
        scope.require_region(stored)
        return _assemble(connection, scope, before_commit)
    except BaseException:
        connection.close()
        raise
