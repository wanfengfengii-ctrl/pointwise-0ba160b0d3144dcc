"""Per-warehouse retirement holds.

Only a warehouse knows which of its own facts are still un-reversed.  When the
catalog asks it to check one version for a retirement, the warehouse records a
hold *in the same transaction* that reads those facts, so a fresh first posting
cannot slip in between the check and the decision.  While a hold is ``pending``
a new first posting of that version is refused; the hold is released when the
retirement is blocked and made permanent when it succeeds.

Holds are keyed by the retirement number.  A delivery for one case can
therefore never release or retire another, and because a released hold is
kept as ``released`` a late replay of the old request cannot re-arm it.
"""

import sqlite3

from energy.versions.handoff import GATE_OPEN, GATE_PENDING, GATE_RETIRED

RELEASED = 'released'


class RetirementGateRepository:
    def __init__(self, connection: sqlite3.Connection):
        self._db = connection

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS retirement_holds (
                retirement_number TEXT PRIMARY KEY NOT NULL,
                version_number TEXT NOT NULL,
                state TEXT NOT NULL
            )
        ''')
        self._db.execute('''
            CREATE INDEX IF NOT EXISTS holds_by_version
            ON retirement_holds(version_number, state)
        ''')

    def find(self, retirement_number: str):
        return self._db.execute('''
            SELECT retirement_number, version_number, state
            FROM retirement_holds WHERE retirement_number = ?
        ''', (retirement_number,)).fetchone()

    def is_retired(self, version_number: str) -> bool:
        return self._db.execute('''
            SELECT 1 FROM retirement_holds
            WHERE version_number = ? AND state = ? LIMIT 1
        ''', (version_number, GATE_RETIRED)).fetchone() is not None

    def gate_state(self, version_number: str) -> str:
        rows = self._db.execute('''
            SELECT state FROM retirement_holds WHERE version_number = ?
        ''', (version_number,)).fetchall()
        states = {row['state'] for row in rows}
        if GATE_RETIRED in states:
            return GATE_RETIRED
        if GATE_PENDING in states:
            return GATE_PENDING
        return GATE_OPEN

    # -- callers supply the surrounding transaction ---------------------------

    def hold_now(self, retirement_number: str, version_number: str) -> None:
        if self.find(retirement_number) is not None:
            return
        if self.is_retired(version_number):
            return
        self._db.execute('''
            INSERT INTO retirement_holds (retirement_number, version_number, state)
            VALUES (?, ?, ?)
        ''', (retirement_number, version_number, GATE_PENDING))

    def make_retired_now(self, retirement_number: str, version_number: str) -> None:
        # Only a case this warehouse already holds can be made permanent.  A
        # forged, replayed or wrong-version notice stays inert.
        row = self.find(retirement_number)
        if row is None or row['version_number'] != version_number:
            return
        if row['state'] == RELEASED:
            return
        if row['state'] != GATE_RETIRED:
            self._db.execute('''
                UPDATE retirement_holds SET state = ? WHERE retirement_number = ?
            ''', (GATE_RETIRED, retirement_number))

    def release_now(self, retirement_number: str, version_number: str) -> None:
        row = self.find(retirement_number)
        if row is None or row['version_number'] != version_number:
            return
        if row['state'] != GATE_PENDING:
            return
        self._db.execute('''
            UPDATE retirement_holds SET state = ? WHERE retirement_number = ?
        ''', (RELEASED, retirement_number))
