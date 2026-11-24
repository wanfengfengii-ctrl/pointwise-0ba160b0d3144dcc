from dataclasses import dataclass
from pathlib import Path

from energy.storage import DomainError, decode_integer, encode_integer, open_database, transaction
from energy.versions.rules import DeviceRule, FrozenVersion

GATE_OPEN = 'open'
GATE_PENDING = 'pending'
GATE_RETIRED = 'retired'


@dataclass(frozen=True, slots=True)
class RetirementRecord:
    retirement_number: str
    version_number: str
    status: str
    blocker_region: str | None = None
    blocker_fact: str | None = None
    decision: str | None = None

    @property
    def blocker(self) -> tuple[str, str] | None:
        if self.status != 'blocked':
            return None
        return (self.blocker_region, self.blocker_fact)


class VersionRepository:
    def __init__(self, path: str | Path):
        self._db = open_database(path)

    def initialize(self) -> None:
        with transaction(self._db, write=True):
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS version_headers (
                    version_number TEXT PRIMARY KEY NOT NULL,
                    retirable INTEGER NOT NULL DEFAULT 0
                )
            ''')
            self._add_column(
                'version_headers', 'retirable',
                'ALTER TABLE version_headers ADD COLUMN retirable INTEGER NOT NULL DEFAULT 0',
            )
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS version_rules (
                    version_number TEXT NOT NULL REFERENCES version_headers(version_number),
                    device TEXT NOT NULL,
                    input_unit TEXT NOT NULL,
                    numerator TEXT NOT NULL,
                    denominator TEXT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY (version_number, device)
                )
            ''')
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS retirements (
                    retirement_number TEXT PRIMARY KEY NOT NULL,
                    version_number TEXT NOT NULL REFERENCES version_headers(version_number),
                    status TEXT NOT NULL,
                    decision TEXT,
                    blocker_region TEXT,
                    blocker_fact TEXT
                )
            ''')
            for column, alteration in (
                ('decision', 'ALTER TABLE retirements ADD COLUMN decision TEXT'),
                ('blocker_region', 'ALTER TABLE retirements ADD COLUMN blocker_region TEXT'),
                ('blocker_fact', 'ALTER TABLE retirements ADD COLUMN blocker_fact TEXT'),
            ):
                self._add_column('retirements', column, alteration)
            self._db.execute('''
                CREATE INDEX IF NOT EXISTS retirements_by_version
                ON retirements(version_number, status)
            ''')

    def _add_column(self, table: str, column: str, alteration: str) -> None:
        names = {row['name'] for row in self._db.execute(f'PRAGMA table_info({table})')}
        if column not in names:
            self._db.execute(alteration)

    def close(self) -> None:
        self._db.close()

    def find_frozen(self, number: str) -> FrozenVersion | None:
        header = self._db.execute('''
            SELECT retirable FROM version_headers WHERE version_number = ?
        ''', (number,)).fetchone()
        if header is None:
            return None
        rows = self._db.execute('''
            SELECT device, input_unit, numerator, denominator, source
            FROM version_rules WHERE version_number = ? ORDER BY device
        ''', (number,)).fetchall()
        rules = tuple(
            DeviceRule(row['device'], row['input_unit'], decode_integer(row['numerator']),
                       decode_integer(row['denominator']), row['source'])
            for row in rows
        )
        return FrozenVersion(number, rules, bool(header['retirable']))

    def save_frozen(self, version: FrozenVersion) -> FrozenVersion:
        with transaction(self._db, write=True):
            stored = self.find_frozen(version.number)
            if stored is not None:
                if stored != version:
                    raise DomainError('conflict', f'version {version.number} is already bound')
                return stored
            self._db.execute(
                'INSERT INTO version_headers (version_number, retirable) VALUES (?, ?)',
                (version.number, 1 if version.retirable else 0),
            )
            self._db.executemany('''
                INSERT INTO version_rules
                    (version_number, device, input_unit, numerator, denominator, source)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                (version.number, rule.device, rule.input_unit, encode_integer(rule.numerator),
                 encode_integer(rule.denominator), rule.source)
                for rule in version.rules
            ))
        return version

    # -- retirement bookkeeping -------------------------------------------------

    def _restore_retirement(self, row) -> RetirementRecord:
        return RetirementRecord(row['retirement_number'], row['version_number'], row['status'],
                                row['blocker_region'], row['blocker_fact'], row['decision'])

    def find_retirement(self, retirement_number: str) -> RetirementRecord | None:
        row = self._db.execute('''
            SELECT retirement_number, version_number, status, decision,
                   blocker_region, blocker_fact
            FROM retirements WHERE retirement_number = ?
        ''', (retirement_number,)).fetchone()
        return None if row is None else self._restore_retirement(row)

    def find_retirement_for_version(self, version_number: str,
                                    status: str) -> RetirementRecord | None:
        row = self._db.execute('''
            SELECT retirement_number, version_number, status, decision,
                   blocker_region, blocker_fact
            FROM retirements WHERE version_number = ? AND status = ?
            ORDER BY rowid LIMIT 1
        ''', (version_number, status)).fetchone()
        return None if row is None else self._restore_retirement(row)

    def gate_state(self, version_number: str) -> str:
        with transaction(self._db):
            if self.find_retirement_for_version(version_number, 'retired') is not None:
                return GATE_RETIRED
            if self.find_retirement_for_version(version_number, 'pending') is not None:
                return GATE_PENDING
            return GATE_OPEN

    def begin_retirement(self, retirement_number: str, version_number: str) -> RetirementRecord:
        with transaction(self._db, write=True):
            stored = self.find_retirement(retirement_number)
            if stored is not None:
                if stored.version_number != version_number:
                    raise DomainError(
                        'conflict',
                        f'retirement {retirement_number} is already bound to '
                        f'{stored.version_number}',
                    )
                return stored
            if self.find_retirement_for_version(version_number, 'retired') is not None:
                raise DomainError('version_retired', f'version {version_number} is already retired')
            if self.find_retirement_for_version(version_number, 'pending') is not None:
                raise DomainError('retirement_in_progress',
                                  f'version {version_number} already has a retirement in progress')
            self._db.execute('''
                INSERT INTO retirements
                    (retirement_number, version_number, status, decision,
                     blocker_region, blocker_fact)
                VALUES (?, ?, 'pending', NULL, NULL, NULL)
            ''', (retirement_number, version_number))
            return self.find_retirement(retirement_number)

    def record_decision(self, retirement_number: str, decision: str,
                        blocker: tuple[str, str] | None = None) -> RetirementRecord:
        """Persist the decision before any notice is delivered.

        Once a decision is recorded a retry can no longer re-evaluate it, so a
        reversal that happens after the decision cannot turn a blocked case
        into a retired one.
        """
        if decision not in ('blocked', 'retired'):
            raise DomainError('invalid_input', f'unknown retirement decision {decision}')
        with transaction(self._db, write=True):
            stored = self.find_retirement(retirement_number)
            if stored is None:
                raise DomainError('unknown_retirement', f'unknown retirement {retirement_number}')
            if stored.decision is not None:
                return stored
            region, fact = blocker if blocker is not None else (None, None)
            self._db.execute('''
                UPDATE retirements
                SET decision = ?, blocker_region = ?, blocker_fact = ?
                WHERE retirement_number = ?
            ''', (decision, region, fact, retirement_number))
            return self.find_retirement(retirement_number)

    def settle_retirement(self, retirement_number: str) -> RetirementRecord:
        with transaction(self._db, write=True):
            stored = self.find_retirement(retirement_number)
            if stored is None:
                raise DomainError('unknown_retirement', f'unknown retirement {retirement_number}')
            if stored.status != 'pending':
                return stored
            if stored.decision is None:
                raise DomainError('conflict',
                                  f'retirement {retirement_number} has no recorded decision')
            self._db.execute('''
                UPDATE retirements SET status = ? WHERE retirement_number = ?
            ''', (stored.decision, retirement_number))
            return self.find_retirement(retirement_number)
