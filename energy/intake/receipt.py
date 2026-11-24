from dataclasses import dataclass
import sqlite3

from energy.intake.rows import SourceRow, decode_source, encode_source
from energy.intake.scope import WarehouseScope
from energy.storage import DomainError, transaction


@dataclass(frozen=True, slots=True)
class BatchReceipt:
    region: str
    business_day: str
    batch_number: str
    receipt_number: str
    row_count: int


@dataclass(frozen=True, slots=True)
class ReceivedBatch:
    receipt: BatchReceipt
    rows: tuple[SourceRow, ...]


class BatchRepository:
    def __init__(self, connection: sqlite3.Connection, scope: WarehouseScope):
        self._db = connection
        self._scope = scope

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS received_batches (
                receipt_number TEXT PRIMARY KEY NOT NULL,
                batch_number TEXT NOT NULL UNIQUE,
                business_day TEXT NOT NULL
            )
        ''')
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS source_rows (
                receipt_number TEXT NOT NULL REFERENCES received_batches(receipt_number),
                position INTEGER NOT NULL,
                row_number TEXT NOT NULL,
                device TEXT NOT NULL,
                input_unit TEXT NOT NULL,
                reading TEXT,
                source TEXT NOT NULL,
                PRIMARY KEY (receipt_number, position),
                UNIQUE (receipt_number, row_number)
            )
        ''')
        self._db.execute('''
            CREATE INDEX IF NOT EXISTS batches_by_day ON received_batches(business_day)
        ''')

    def _restore(self, header: sqlite3.Row | None) -> ReceivedBatch | None:
        if header is None:
            return None
        number = header['receipt_number']
        raw_rows = self._db.execute('''
            SELECT row_number, device, input_unit, reading, source
            FROM source_rows WHERE receipt_number = ? ORDER BY position
        ''', (number,)).fetchall()
        rows = tuple(decode_source(*row) for row in raw_rows)
        receipt = BatchReceipt(self._scope.region, header['business_day'],
                               header['batch_number'], number, len(rows))
        return ReceivedBatch(receipt, rows)

    def find_by_number(self, batch_number: str) -> ReceivedBatch | None:
        header = self._db.execute('''
            SELECT receipt_number, batch_number, business_day
            FROM received_batches WHERE batch_number = ?
        ''', (batch_number,)).fetchone()
        return self._restore(header)

    def find_by_receipt(self, receipt_number: str) -> ReceivedBatch | None:
        header = self._db.execute('''
            SELECT receipt_number, batch_number, business_day
            FROM received_batches WHERE receipt_number = ?
        ''', (receipt_number,)).fetchone()
        return self._restore(header)

    def store_once(self, batch_number: str, business_day: str,
                   rows: tuple[SourceRow, ...]) -> BatchReceipt:
        with transaction(self._db, write=True):
            previous = self.find_by_number(batch_number)
            if previous is not None:
                if previous.receipt.business_day != business_day or previous.rows != rows:
                    raise DomainError('conflict', f'batch {batch_number} is already bound')
                return previous.receipt
            receipt_number = self._scope.qualify('batch', batch_number)
            self._db.execute('''
                INSERT INTO received_batches (receipt_number, batch_number, business_day)
                VALUES (?, ?, ?)
            ''', (receipt_number, batch_number, business_day))
            self._db.executemany('''
                INSERT INTO source_rows
                    (receipt_number, position, row_number, device, input_unit, reading, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', ((receipt_number, position, *encode_source(row))
                  for position, row in enumerate(rows)))
            receipt = BatchReceipt(self._scope.region, business_day, batch_number,
                                   receipt_number, len(rows))
        return receipt
