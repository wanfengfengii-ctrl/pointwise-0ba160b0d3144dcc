from dataclasses import dataclass
import sqlite3

from energy.conversion.repository import Preview, PreviewRepository
from energy.intake.scope import WarehouseScope
from energy.storage import CommitHook, DomainError, transaction


@dataclass(frozen=True, slots=True)
class Fact:
    fact_number: str
    sequence: int
    preview: Preview


@dataclass(frozen=True, slots=True)
class FactReceipt:
    request_number: str
    fact: Fact


@dataclass(frozen=True, slots=True)
class ReversalReceipt:
    region: str
    request_number: str
    reversal_number: str
    fact_number: str


class FactRepository:
    def __init__(self, connection: sqlite3.Connection, scope: WarehouseScope,
                 previews: PreviewRepository, before_commit: CommitHook | None = None):
        self._db = connection
        self._scope = scope
        self._previews = previews
        self._before_commit = before_commit

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS facts (
                sequence INTEGER PRIMARY KEY,
                fact_number TEXT NOT NULL UNIQUE,
                preview_number TEXT NOT NULL UNIQUE REFERENCES previews(number)
            )
        ''')
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS post_receipts (
                request_number TEXT PRIMARY KEY NOT NULL,
                fact_number TEXT NOT NULL UNIQUE REFERENCES facts(fact_number)
            )
        ''')
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS reversals (
                reversal_number TEXT PRIMARY KEY NOT NULL,
                request_number TEXT NOT NULL UNIQUE,
                fact_number TEXT NOT NULL UNIQUE REFERENCES facts(fact_number)
            )
        ''')

    def _restore_fact(self, row: sqlite3.Row) -> Fact:
        preview = self._previews.find_by_number(row['preview_number'])
        if preview is None:
            raise sqlite3.DatabaseError('fact refers to a missing preview')
        return Fact(row['fact_number'], row['sequence'], preview)

    def get_post_receipt(self, request_number: str) -> FactReceipt | None:
        row = self._db.execute('''
            SELECT f.fact_number, f.sequence, f.preview_number
            FROM post_receipts AS r JOIN facts AS f USING (fact_number)
            WHERE r.request_number = ?
        ''', (request_number,)).fetchone()
        if row is None:
            return None
        return FactReceipt(request_number, self._restore_fact(row))

    def commit_post(self, request_number: str, preview_number: str) -> FactReceipt:
        with transaction(self._db, write=True):
            previous = self.get_post_receipt(request_number)
            if previous is not None:
                if previous.fact.preview.number != preview_number:
                    raise DomainError('conflict', f'post request {request_number} is already bound')
                return previous
            preview = self._previews.find_by_number(preview_number)
            if preview is None:
                raise DomainError('unknown_preview', f'unknown preview {preview_number}')
            occupied = self._db.execute('''
                SELECT fact_number FROM facts WHERE preview_number = ?
            ''', (preview_number,)).fetchone()
            if occupied is not None:
                raise DomainError('already_posted', f'preview already posted as {occupied[0]}')

            fact_number = self._scope.qualify('fact', request_number)
            cursor = self._db.execute('''
                INSERT INTO facts (fact_number, preview_number) VALUES (?, ?)
            ''', (fact_number, preview_number))
            self._db.execute('''
                INSERT INTO post_receipts (request_number, fact_number) VALUES (?, ?)
            ''', (request_number, fact_number))
            receipt = FactReceipt(request_number, Fact(fact_number, cursor.lastrowid, preview))
            if self._before_commit is not None:
                self._before_commit('post')
        return receipt

    def get_reversal_receipt(self, request_number: str) -> ReversalReceipt | None:
        row = self._db.execute('''
            SELECT reversal_number, fact_number FROM reversals WHERE request_number = ?
        ''', (request_number,)).fetchone()
        if row is None:
            return None
        return ReversalReceipt(self._scope.region, request_number,
                               row['reversal_number'], row['fact_number'])

    def commit_reversal(self, request_number: str, fact_number: str) -> ReversalReceipt:
        with transaction(self._db, write=True):
            previous = self.get_reversal_receipt(request_number)
            if previous is not None:
                if previous.fact_number != fact_number:
                    raise DomainError('conflict', f'reversal request {request_number} is already bound')
                return previous
            target = self._db.execute('''
                SELECT fact_number FROM facts WHERE fact_number = ?
            ''', (fact_number,)).fetchone()
            if target is None:
                raise DomainError('unknown_fact', f'unknown fact {fact_number}')
            reversed_row = self._db.execute('''
                SELECT reversal_number FROM reversals WHERE fact_number = ?
            ''', (fact_number,)).fetchone()
            if reversed_row is not None:
                raise DomainError('already_reversed', f'fact already reversed by {reversed_row[0]}')
            reversal_number = self._scope.qualify('reversal', request_number)
            self._db.execute('''
                INSERT INTO reversals (reversal_number, request_number, fact_number)
                VALUES (?, ?, ?)
            ''', (reversal_number, request_number, fact_number))
            receipt = ReversalReceipt(self._scope.region, request_number, reversal_number, fact_number)
            if self._before_commit is not None:
                self._before_commit('reverse')
        return receipt

    def list_effective(self, business_day: str) -> tuple[Fact, ...]:
        with transaction(self._db):
            rows = self._db.execute('''
                SELECT f.fact_number, f.sequence, f.preview_number
                FROM received_batches AS b
                JOIN previews AS p USING (receipt_number)
                JOIN facts AS f ON f.preview_number = p.number
                WHERE b.business_day = ? AND NOT EXISTS (
                    SELECT 1 FROM reversals AS r WHERE r.fact_number = f.fact_number
                )
                ORDER BY f.sequence
            ''', (business_day,)).fetchall()
            return tuple(self._restore_fact(row) for row in rows)
