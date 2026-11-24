from pathlib import Path

from energy.reports.snapshot import ReportSnapshot, decode_snapshot, encode_snapshot
from energy.storage import CommitHook, DomainError, open_database, transaction


def require_same_binding(snapshot: ReportSnapshot, region: str, business_day: str) -> None:
    if (snapshot.region, snapshot.business_day) != (region, business_day):
        raise DomainError('conflict', f'report {snapshot.number} is already bound')


class ReportRepository:
    def __init__(self, path: str | Path, *, before_commit: CommitHook | None = None):
        self._db = open_database(path)
        self._before_commit = before_commit

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS report_snapshots (
                number TEXT PRIMARY KEY NOT NULL,
                payload TEXT NOT NULL
            )
        ''')

    def close(self) -> None:
        self._db.close()

    def find(self, number: str) -> ReportSnapshot | None:
        stored = self._db.execute('''
            SELECT payload FROM report_snapshots WHERE number = ?
        ''', (number,)).fetchone()
        return None if stored is None else decode_snapshot(stored['payload'])

    def store_once(self, snapshot: ReportSnapshot) -> ReportSnapshot:
        with transaction(self._db, write=True):
            stored = self.find(snapshot.number)
            if stored is not None:
                require_same_binding(stored, snapshot.region, snapshot.business_day)
                return stored
            self._db.execute('''
                INSERT INTO report_snapshots (number, payload) VALUES (?, ?)
            ''', (snapshot.number, encode_snapshot(snapshot)))
            if self._before_commit is not None:
                self._before_commit('report')
        return snapshot
