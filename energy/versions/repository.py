from pathlib import Path

from energy.storage import DomainError, decode_integer, encode_integer, open_database, transaction
from energy.versions.rules import DeviceRule, FrozenVersion


class VersionRepository:
    def __init__(self, path: str | Path):
        self._db = open_database(path)

    def initialize(self) -> None:
        with transaction(self._db, write=True):
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS version_headers (
                    version_number TEXT PRIMARY KEY NOT NULL
                )
            ''')
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

    def close(self) -> None:
        self._db.close()

    def find_frozen(self, number: str) -> FrozenVersion | None:
        rows = self._db.execute('''
            SELECT device, input_unit, numerator, denominator, source
            FROM version_rules WHERE version_number = ? ORDER BY device
        ''', (number,)).fetchall()
        if not rows:
            return None
        rules = tuple(
            DeviceRule(row['device'], row['input_unit'], decode_integer(row['numerator']),
                       decode_integer(row['denominator']), row['source'])
            for row in rows
        )
        return FrozenVersion(number, rules)

    def save_frozen(self, version: FrozenVersion) -> FrozenVersion:
        with transaction(self._db, write=True):
            stored = self.find_frozen(version.number)
            if stored is not None:
                if stored != version:
                    raise DomainError('conflict', f'version {version.number} is already bound')
                return stored
            self._db.execute('INSERT INTO version_headers VALUES (?)', (version.number,))
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
