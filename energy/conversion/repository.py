from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3

from energy.conversion.quantities import decode_fraction, decode_quantity, encode_quantity
from energy.conversion.units import OUTPUT_UNIT
from energy.intake.receipt import BatchReceipt
from energy.intake.rows import SourceRow, decode_source
from energy.intake.scope import WarehouseScope
from energy.storage import transaction


@dataclass(frozen=True, slots=True)
class PreviewLine:
    position: int
    source: SourceRow
    coefficient: Fraction
    rule_source: str
    quantity: Fraction | None


@dataclass(frozen=True, slots=True)
class Preview:
    number: str
    region: str
    business_day: str
    batch_number: str
    receipt_number: str
    version_number: str
    lines: tuple[PreviewLine, ...]
    unit: str = OUTPUT_UNIT


class PreviewRepository:
    def __init__(self, connection: sqlite3.Connection, scope: WarehouseScope):
        self._db = connection
        self._scope = scope

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS previews (
                number TEXT PRIMARY KEY NOT NULL,
                receipt_number TEXT NOT NULL REFERENCES received_batches(receipt_number),
                version_number TEXT NOT NULL,
                unit TEXT NOT NULL,
                UNIQUE (receipt_number, version_number)
            )
        ''')
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS preview_lines (
                preview_number TEXT NOT NULL REFERENCES previews(number),
                position INTEGER NOT NULL,
                coefficient TEXT NOT NULL,
                rule_source TEXT NOT NULL,
                quantity TEXT,
                PRIMARY KEY (preview_number, position)
            )
        ''')

    def find_by_binding(self, receipt_number: str, version_number: str) -> Preview | None:
        header = self._db.execute('''
            SELECT number FROM previews WHERE receipt_number = ? AND version_number = ?
        ''', (receipt_number, version_number)).fetchone()
        if header is None:
            return None
        return self.find_by_number(header['number'])

    def find_by_number(self, number: str) -> Preview | None:
        header = self._db.execute('''
            SELECT p.number, p.receipt_number, p.version_number, p.unit,
                   b.business_day, b.batch_number
            FROM previews AS p JOIN received_batches AS b USING (receipt_number)
            WHERE p.number = ?
        ''', (number,)).fetchone()
        if header is None:
            return None
        # Source rows are immutable and are shared with all previews of the same batch.
        rows = self._db.execute('''
            SELECT l.position, s.row_number, s.device, s.input_unit, s.reading, s.source,
                   l.coefficient, l.rule_source, l.quantity
            FROM preview_lines AS l
            JOIN source_rows AS s ON s.receipt_number = ? AND s.position = l.position
            WHERE l.preview_number = ? ORDER BY l.position
        ''', (header['receipt_number'], number)).fetchall()
        lines = tuple(
            PreviewLine(row['position'], decode_source(*row[1:6]),
                        decode_fraction(row['coefficient']), row['rule_source'],
                        decode_quantity(row['quantity']))
            for row in rows
        )
        return Preview(number, self._scope.region, header['business_day'], header['batch_number'],
                       header['receipt_number'], header['version_number'], lines, header['unit'])

    def store_once(self, receipt: BatchReceipt, version_number: str,
                   lines: tuple[PreviewLine, ...]) -> Preview:
        with transaction(self._db, write=True):
            stored = self.find_by_binding(receipt.receipt_number, version_number)
            if stored is not None:
                return stored
            binding = json.dumps([receipt.receipt_number, version_number], separators=(',', ':'))
            number = self._scope.qualify('preview', binding)
            self._db.execute('''
                INSERT INTO previews (number, receipt_number, version_number, unit)
                VALUES (?, ?, ?, ?)
            ''', (number, receipt.receipt_number, version_number, OUTPUT_UNIT))
            self._db.executemany('''
                INSERT INTO preview_lines (preview_number, position, coefficient, rule_source, quantity)
                VALUES (?, ?, ?, ?, ?)
            ''', ((number, line.position, encode_quantity(line.coefficient), line.rule_source,
                   encode_quantity(line.quantity)) for line in lines))
            preview = Preview(number, self._scope.region, receipt.business_day, receipt.batch_number,
                              receipt.receipt_number, version_number, lines)
        return preview
